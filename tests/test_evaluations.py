import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_api import sse_events

import agenttinker.storage.evaluations as assessment_module
from agenttinker.api.app import create_app
from agenttinker.core.projection import project_events
from agenttinker.core.records import Run, VersionRef
from agenttinker.experiments.evaluation import EvaluationRequest, ReviewRequest
from agenttinker.runtime.checkpoints import checkpoint_path
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunRequest, RunService
from agenttinker.storage.evaluations import AssessmentRejected, SQLiteEvaluationStore
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore


@pytest.fixture
def document(tmp_path):
    database = tmp_path / "runs.sqlite"
    with RunService(database) as service:
        view, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "run-A")
        view = service.wait(view.run.run_id)
    return database, view


def review_request(evaluation, **changes):
    return ReviewRequest.model_validate(
        {
            "evaluation_id": evaluation.evaluation_id,
            "input_hash": evaluation.input_hash,
            "reviewer": "offline test reviewer",
            "judgement": "justified_insufficiency",
            "fact_coverage": {"configurable-retries": "covered", "citation-fix": "missing"},
            "explanation": "离线测试标签：回答明确说明引用修复材料不足。",
            **changes,
        }
    )


def test_concurrent_evaluation_identity_and_restart_need_no_runtime_state(document):
    database, view = document
    with SQLiteEventStore(database) as store:
        original = store.events(view.run.run_id)
    checkpoint_path(database).unlink()

    def evaluate(_):
        with SQLiteEvaluationStore(database) as store:
            return store.create_evaluation(view.run.run_id, EvaluationRequest(), "evaluation-A")

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(evaluate, range(8)))
    assert sum(created for _, created in results) == 1
    assert len({result.evaluation_id for result, _ in results}) == 1
    expected = results[0][0]
    assert expected.status == "completed" and expected.answer_review == "unreviewed"
    assert [c.verdict for c in expected.checks] == ["fail", "fail", "pass"]
    with SQLiteEvaluationStore(database) as store:
        assert store.create_evaluation(view.run.run_id, EvaluationRequest(), "evaluation-A") == (
            expected,
            False,
        )
        assert store.get_view(view.run.run_id) == view
        assert store.events(view.run.run_id) == original
        assert store.evaluations(view.run.run_id).total == 1
        with pytest.raises(EventConflict):
            store.create_evaluation("another-run", EvaluationRequest(), "evaluation-A")
    assert not checkpoint_path(database).exists()


def test_fork_evaluation_resolves_shared_prefix_through_multiple_ancestors(document):
    database, a = document
    with RunService(database) as service:
        b, _ = service.fork(
            a.run.run_id,
            ForkRequest(
                source_checkpoint_id=a.checkpoints[0].checkpoint_id,
                patch={"top_k": 3},
            ),
            "run-B",
        )
        b = service.wait(b.run.run_id)
        c, _ = service.fork(
            b.run.run_id,
            ForkRequest(
                source_checkpoint_id=b.checkpoints[0].checkpoint_id,
                patch={"top_k": 2},
            ),
            "run-C",
        )
        c = service.wait(c.run.run_id)
    with SQLiteEvaluationStore(database) as store:
        for view, expected in ((b, ["pass"] * 3), (c, ["fail", "fail", "pass"])):
            assert store.inherited_spans(view) == (a.spans[0],)
            result, _ = store.create_evaluation(
                view.run.run_id, EvaluationRequest(), view.run.run_id
            )
            assert [check.verdict for check in result.checks] == expected
            assert result.sample_size == 1 and not result.statistical_conclusion


def test_precondition_rejection_does_not_consume_identity_or_invent_scores(document):
    database, view = document
    now = datetime.now(UTC)
    queued = Run(
        run_id="queued", mode="synthetic", config=view.run.config, created_at=now, updated_at=now
    )
    with SQLiteEvaluationStore(database) as store:
        store.create_requested_run(queued, "queued", "fixture")
        with pytest.raises(AssessmentRejected, match="evaluation_run_active"):
            store.create_evaluation("queued", EvaluationRequest(), "later")
        with pytest.raises(AssessmentRejected, match="evaluator_unsupported"):
            store.create_evaluation(
                view.run.run_id,
                EvaluationRequest(
                    evaluator=VersionRef(id="arbitrary-script", version="1"),
                ),
                "later",
            )
        result, created = store.create_evaluation(view.run.run_id, EvaluationRequest(), "later")
        assert created and result.execution_status == "succeeded"
    with RunService(database) as service:
        legacy, _ = service.submit(RunRequest(mode="synthetic"), "legacy")
        legacy = service.wait(legacy.run.run_id)
    with SQLiteEvaluationStore(database) as store:
        with pytest.raises(AssessmentRejected, match="evaluation_context_mismatch"):
            store.create_evaluation(legacy.run.run_id, EvaluationRequest(), "legacy-evaluation")
        assert store.evaluations(legacy.run.run_id).total == 0


def test_reviews_bind_exact_evidence_and_append_without_rewriting_prior_judgements(document):
    database, view = document
    with SQLiteEvaluationStore(database) as store:
        evaluation, _ = store.create_evaluation(view.run.run_id, EvaluationRequest(), "eval")
        with pytest.raises(AssessmentRejected, match="review_evidence_mismatch"):
            store.create_review(
                view.run.run_id, review_request(evaluation, input_hash="0" * 64), "review"
            )
        with pytest.raises(AssessmentRejected, match="assessment_not_found"):
            store.create_review("other-run", review_request(evaluation), "review")
        first, created = store.create_review(view.run.run_id, review_request(evaluation), "review")
        assert created and first.judgement == "justified_insufficiency"
        assert store.create_review(view.run.run_id, review_request(evaluation), "review") == (
            first,
            False,
        )
        changed = review_request(
            evaluation, judgement="uncertain", explanation="另一份离线复核意见。"
        )
        with pytest.raises(EventConflict):
            store.create_review(view.run.run_id, changed, "review")
        second, _ = store.create_review(view.run.run_id, changed, "new-review")
        assert store.get_review(view.run.run_id, first.review_id) == first
        assert store.reviews(view.run.run_id).items == (second, first)
        assert store.get_evaluation(view.run.run_id, evaluation.evaluation_id) == evaluation
        assert store.get_view(view.run.run_id) == view


def test_assessments_and_identity_ledger_are_append_only_and_commit_atomically(document):
    database, view = document
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_ledger BEFORE INSERT ON assessment_requests "
            "BEGIN SELECT RAISE(ABORT, 'injected_commit_failure'); END"
        )
    with SQLiteEvaluationStore(database) as store:
        with pytest.raises(sqlite3.IntegrityError, match="injected_commit_failure"):
            store.create_evaluation(view.run.run_id, EvaluationRequest(), "eval")
        assert store.evaluations(view.run.run_id).total == 0
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_ledger")
    with SQLiteEvaluationStore(database) as store:
        evaluation, _ = store.create_evaluation(view.run.run_id, EvaluationRequest(), "eval")
        store.create_review(view.run.run_id, review_request(evaluation), "review")
    with sqlite3.connect(database) as connection:
        for table in ("evaluations", "reviews", "assessment_requests"):
            for operation in (f"UPDATE {table} SET rowid=rowid", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="assessments_append_only"):
                    connection.execute(operation)


def test_evaluator_failure_is_preserved_separately_and_not_a_zero_score(document, monkeypatch):
    database, view = document

    def failed(*_args):
        raise RuntimeError("sensitive exception text must not enter the assessment")

    with SQLiteEvaluationStore(database) as store:
        with monkeypatch.context() as context:
            context.setattr(assessment_module, "evaluate_documents", failed)
            result, _ = store.create_evaluation(view.run.run_id, EvaluationRequest(), "failed-eval")
        assert result.status == "failed" and result.failure_code == "evaluator_error:RuntimeError"
        assert result.execution_status == "succeeded" and result.checks == ()
        assert "sensitive" not in result.model_dump_json()
        assert store.create_evaluation(view.run.run_id, EvaluationRequest(), "failed-eval") == (
            result,
            False,
        )
        with pytest.raises(AssessmentRejected, match="review_evaluation_failed"):
            store.create_review(view.run.run_id, review_request(result), "review")
        new, _ = store.create_evaluation(
            view.run.run_id, EvaluationRequest(), "explicit-reevaluation"
        )
        assert new.status == "completed" and new.input_hash == result.input_hash
        assert store.evaluations(view.run.run_id).total == 2
        assert store.get_view(view.run.run_id) == view


def test_assessment_pagination_keeps_all_results_and_reports_total(document):
    database, view = document
    with SQLiteEvaluationStore(database) as store:
        results = [
            store.create_evaluation(view.run.run_id, EvaluationRequest(), f"eval-{i}")[0]
            for i in range(3)
        ]
        for i, result in enumerate(results):
            store.create_review(view.run.run_id, review_request(result), f"review-{i}")
        for method in (store.evaluations, store.reviews):
            first = method(view.run.run_id, limit=2)
            second = method(view.run.run_id, offset=first.next_offset, limit=2)
            assert first.total == second.total == 3
            assert len(first.items) == 2 and len(second.items) == 1 and second.next_offset is None
            assert method(view.run.run_id, offset=3).items == ()
            with pytest.raises(ValueError):
                method(view.run.run_id, limit=True)
        assert store.evaluations(view.run.run_id).items == tuple(reversed(results))


def test_v2_database_migration_preserves_old_run_events_and_request_fingerprint(document):
    database, view = document
    with RunService(database) as service:
        request = RunRequest(mode="synthetic")
        legacy, _ = service.submit(request, "legacy-request")
        legacy = service.wait(legacy.run.run_id)
    with SQLiteEventStore(database) as store:
        original = store.events(legacy.run.run_id)
    # Exact v2 table set: remove only empty assessment tables before reopening.
    with sqlite3.connect(database) as connection:
        for table in ("assessment_requests", "reviews", "evaluations"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version=2")
    with SQLiteEvaluationStore(database) as store:
        expected = hashlib.sha256(
            json.dumps(request.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        assert store.request_run("legacy-request", expected) == legacy
        assert store.events(legacy.run.run_id) == original
        assert store.get_view(view.run.run_id) == view
        store.create_evaluation(view.run.run_id, EvaluationRequest(), "post-migration")
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_http_evaluation_review_idempotency_errors_and_no_key_restart(document, monkeypatch):
    database, view = document
    route = f"/api/v1/runs/{view.run.run_id}"
    with TestClient(create_app(database)) as client:
        before = client.get(route + "/events").text
        response = client.post(route + "/evaluations", json={}, headers={"Idempotency-Key": "eval"})
        assert response.status_code == 201
        evaluation = response.json()
        assert client.get(response.headers["location"]).json() == evaluation
        assert client.get(route + "/evaluations").json()["total"] == 1
        body = review_request(
            assessment_module.EvaluationResult.model_validate(evaluation)
        ).model_dump(mode="json")
        review = client.post(route + "/reviews", json=body, headers={"Idempotency-Key": "review"})
        assert review.status_code == 201
        assert client.get(review.headers["location"]).json() == review.json()
        assert (
            client.post(
                route + "/reviews", json=body, headers={"Idempotency-Key": "review"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                route + "/reviews",
                json={**body, "judgement": "uncertain"},
                headers={"Idempotency-Key": "review"},
            ).status_code
            == 409
        )
        bad = client.post(
            route + "/reviews",
            json={**body, "input_hash": "0" * 64},
            headers={"Idempotency-Key": "bad"},
        )
        assert bad.status_code == 409 and bad.json()["detail"] == "review_evidence_mismatch"
        unsupported = client.post(
            route + "/evaluations",
            json={"evaluator": {"id": "script", "version": "1"}},
            headers={"Idempotency-Key": "unsupported"},
        )
        assert (
            unsupported.status_code == 422
            and unsupported.json()["detail"] == "evaluator_unsupported"
        )
        assert (
            client.post(
                route + "/reviews",
                json={**body, "fact_coverage": {}},
                headers={"Idempotency-Key": "invalid"},
            ).status_code
            == 422
        )
        assert client.get(route + "/evaluations/missing").status_code == 404
        assert client.get(route + "/reviews?limit=101").status_code == 422
        assert client.get(route + "/events").text == before
        assert project_events(sse_events(before.splitlines())) == view
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(create_app(database)) as client:
        assert (
            client.post(route + "/evaluations", json={}, headers={"Idempotency-Key": "eval"}).json()
            == evaluation
        )
        assert client.get(route + "/reviews").json()["items"] == [review.json()]
