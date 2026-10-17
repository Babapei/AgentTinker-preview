"""Offline package imports preserve evidence without granting execution authority."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_packages import finished_pair, resign

from agenttinker.api.app import create_app
from agenttinker.core.projection import project_events
from agenttinker.core.records import Artifact
from agenttinker.experiments.evaluation import EvaluationRequest, ReviewRequest
from agenttinker.packages.exporting import export_run, make_package
from agenttinker.packages.models import (
    MAX_PACKAGE_BYTES,
    PackageRejected,
    PortableArtifact,
    PortableRun,
    RecordSource,
    canonical,
    digest,
)
from agenttinker.packages.portable import observation_view
from agenttinker.runtime.checkpoints import ForkRejected, checkpoint_path
from agenttinker.runtime.service import ForkRequest, RunService
from agenttinker.storage.evaluations import AssessmentRejected
from agenttinker.storage.packages import SQLitePackageStore
from agenttinker.storage.sqlite import EventConflict


@pytest.fixture
def source(tmp_path):
    database = tmp_path / "source.sqlite"
    a, b = finished_pair(database)
    with SQLitePackageStore(database) as store:
        evaluation, _ = store.create_evaluation(b.run.run_id, EvaluationRequest(), "eval")
        review, _ = store.create_review(
            b.run.run_id,
            ReviewRequest(
                evaluation_id=evaluation.evaluation_id,
                input_hash=evaluation.input_hash,
                reviewer="offline test fixture",
                fact_coverage={"configurable-retries": "covered", "citation-fix": "covered"},
                judgement="uncertain",
                explanation="导入契约离线夹具，不代表真实人工评价。",
            ),
            "review",
        )
    return database, a, b, evaluation, review, export_run(database, b.run.run_id)


def trace_package(view, *, status=None, files=None):
    snapshot = observation_view(view, playback=False).model_dump(mode="json")
    if status:
        snapshot["run"]["status"] = status
    record = PortableRun.model_validate(
        {
            "source": RecordSource(
                run_id=view.run.run_id, mode=view.run.mode, view_sha256=digest(view)
            ).model_dump(mode="json"),
            "view": snapshot,
        }
    )
    return make_package(
        {f"runs/{view.run.run_id}.json": record.model_dump(mode="json"), **(files or {})},
        root_run_id=view.run.run_id,
        title="External normalized observation",
        kind="trace",
    )


def counts(database):
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "runs",
                "events",
                "artifacts",
                "imports",
                "import_runs",
                "import_requests",
            )
        }


def test_round_trip_maps_lineage_without_overwriting_native_records_or_source_opinions(source):
    database, a, b, evaluation, review, package = source
    with SQLitePackageStore(database) as store:
        originals = {v.run.run_id: store.events(v.run.run_id) for v in (a, b)}
        result, created = store.import_data(canonical(package), "import")
        assert created and result.source_package_sha256 == digest(package)
        assert result.portable_package_sha256 == digest(store.package_for_run(result.root_run_id))
        local = {link.source_run_id: store.get_view(link.local_run_id) for link in result.runs}
        local_a, local_b = local[a.run.run_id], local[b.run.run_id]
        assert result.root_run_id == local_b.run.run_id != b.run.run_id
        assert local_b.run.parent_run_id == local_a.run.run_id
        assert local_b.run.source_checkpoint_id == local_a.checkpoints[0].checkpoint_id
        assert local_b.run.intervention.parent_run_id == local_a.run.run_id
        assert local_b.run.intervention.before == b.run.intervention.before
        assert local_b.run.intervention.after == b.run.intervention.after
        assert local_b.run.inherited_span_ids == (local_a.spans[0].span_id,)
        for original in (a, b):
            view = local[original.run.run_id]
            assert view.run.mode == "imported" and view.run.config == original.run.config
            assert view.run.status == original.run.status
            assert not view.run.capabilities.run_from_start
            assert not view.run.capabilities.fork_from_checkpoint
            assert view.run.capabilities.record_playback
            assert all(not cp.locator and not cp.allowed_patch_fields for cp in view.checkpoints)
            assert project_events(store.events(view.run.run_id)) == view
            assert store.rebuild_view(view.run.run_id) == view
            for span, old in zip(view.spans, original.spans, strict=True):
                assert span.span_id != old.span_id and span.run_id == view.run.run_id
                assert span.logical_call_id == old.logical_call_id
                assert span.call_index == old.call_index and span.attempt == old.attempt
                expected_input = dict(old.input) if old.input is not None else None
                if expected_input and "intervention_id" in expected_input:
                    expected_input["intervention_id"] = view.run.intervention.intervention_id
                assert span.input == expected_input and span.output == old.output
                assert span.usage == old.usage and span.cost == old.cost
            assert store.get_view(original.run.run_id) == original
            assert store.events(original.run.run_id) == originals[original.run.run_id]
        provenance = store.provenance(local_b.run.run_id)
        assert provenance.source_mode == "synthetic"
        assert provenance.source_run_id == b.run.run_id
        assert provenance.source_view_sha256 == digest(b)
        assert provenance.claim == "unverified_source_record"
        assert provenance.evaluations == (evaluation,) and provenance.reviews == (review,)
        binding = provenance.evaluation_bindings[0]
        assert binding.source_input_hash == evaluation.input_hash
        assert binding.portable_input_hash != evaluation.input_hash
        assert store.evaluations(local_b.run.run_id).total == 0
        assert store.reviews(local_b.run.run_id).total == 0
        assert store.provenance(a.run.run_id) is None
    assert export_run(database, result.root_run_id) == package


def test_concurrent_import_and_restart_deduplicate_content_and_keep_request_conflicts(
    source, tmp_path
):
    _, _, _, _, _, package = source
    database = tmp_path / "import.sqlite"
    # The API owner initializes the database before accepting concurrent requests.
    with SQLitePackageStore(database):
        pass

    def save(key):
        with SQLitePackageStore(database) as store:
            return store.import_data(canonical(package), key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(save, ["same", "same", "second", "third"]))
    assert sum(created for _, created in results) == 1
    result = results[0][0]
    assert all(value == result for value, _ in results)
    assert counts(database)["runs"] == 2 and counts(database)["import_requests"] == 3
    with SQLitePackageStore(database) as store:
        # Whitespace does not change the validated canonical content identity.
        assert store.import_data(json.dumps(package.model_dump(mode="json")).encode(), "same") == (
            result,
            False,
        )
        assert store.get_import(result.import_id) == result
        changed = package.model_dump(mode="json")
        changed["manifest"]["title"] = "Different source package"
        before = counts(database)
        with pytest.raises(EventConflict, match="idempotency_key_payload_conflict"):
            store.import_data(canonical(changed), "same")
        assert counts(database) == before
    assert not checkpoint_path(database).exists()


def test_import_failure_rolls_back_all_database_records_and_can_retry(source, tmp_path):
    _, _, _, _, _, package = source
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        store._connection.execute(
            "CREATE TRIGGER fail_final_import BEFORE INSERT ON import_requests "
            "BEGIN SELECT RAISE(ABORT, 'offline injected failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="offline injected failure"):
            store.import_data(canonical(package), "import")
        assert not any(counts(database).values())
        store._connection.execute("DROP TRIGGER fail_final_import")
        result, created = store.import_data(canonical(package), "import")
        assert created and store.get_view(result.root_run_id).run.mode == "imported"


def test_forged_execution_flags_locators_and_credential_fields_are_never_persisted(
    source, tmp_path
):
    _, a, _, _, _, package = source
    data = package.model_dump(mode="json")
    record = data["files"][f"runs/{a.run.run_id}.json"]
    caps = {
        **record["view"]["run"]["capabilities"],
        "run_from_start": True,
        "fork_from_checkpoint": True,
        "patch_tool_policy": True,
    }
    record["view"]["run"]["capabilities"] = caps
    record["events"][0]["data"]["capabilities"] = caps
    record["view"]["checkpoints"][0]["locator"] = {"api_key": "offline-private-locator"}
    record["view"]["checkpoints"][0]["allowed_patch_fields"] = ["top_k"]
    for event in record["events"]:
        if (
            event["type"] == "checkpoint.saved"
            and event["data"]["checkpoint_id"] == record["view"]["checkpoints"][0]["checkpoint_id"]
        ):
            event["data"] = record["view"]["checkpoints"][0]
    # Change both the frozen start and finish input so event projection remains valid.
    span_id = record["view"]["spans"][0]["span_id"]
    record["view"]["spans"][0]["input"]["Authorization"] = "offline-private-token"
    for event in record["events"]:
        if event["type"] in {"span.started", "span.finished"} and event["span_id"] == span_id:
            event["data"]["input"]["Authorization"] = "offline-private-token"
    # The B evaluation is tied to A's inherited prefix, so this edited source has no opinions.
    for value in data["files"].values():
        if "source" in value and "view" in value:
            value.update(evaluations=[], reviews=[], evaluation_bindings=[])
    encoded = resign(data)
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        result, _ = store.import_data(encoded, "import")
        portable = store.package_for_run(result.root_run_id)
        assert result.source_package_sha256 != result.portable_package_sha256
        assert b"offline-private" not in canonical(portable)
        for link in result.runs:
            view = store.get_view(link.local_run_id)
            assert not view.run.capabilities.run_from_start
            assert not view.run.capabilities.fork_from_checkpoint
            assert all(not cp.locator and not cp.allowed_patch_fields for cp in view.checkpoints)
            assert "offline-private" not in view.model_dump_json()
            assert "offline-private" not in "".join(
                e.model_dump_json() for e in store.events(link.local_run_id)
            )
    assert b"offline-private" not in canonical(export_run(database, result.root_run_id))
    assert not checkpoint_path(database).exists()


def test_active_summary_stays_observational_across_restart_and_all_write_actions_reject(
    source, tmp_path
):
    _, a, _, evaluation, _, _ = source
    package = trace_package(a, status="running")
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        result, _ = store.import_data(canonical(package), "import")
        original = store.get_view(result.root_run_id)
        assert not original.run.capabilities.record_playback
        assert not store.events(result.root_run_id)
    with RunService(
        database, model_factory=lambda _: pytest.fail("import dispatched SDK")
    ) as service:
        with SQLitePackageStore(database) as store:
            assert store.get_view(result.root_run_id) == original
            with pytest.raises(AssessmentRejected, match="imported_record_read_only"):
                store.create_evaluation(result.root_run_id, EvaluationRequest(), "eval")
            with pytest.raises(AssessmentRejected, match="imported_record_read_only"):
                store.create_review(
                    result.root_run_id,
                    ReviewRequest(
                        evaluation_id=evaluation.evaluation_id,
                        input_hash=evaluation.input_hash,
                        reviewer="offline",
                        fact_coverage={
                            "configurable-retries": "uncertain",
                            "citation-fix": "uncertain",
                        },
                        judgement="uncertain",
                        explanation="Must reject imported observations.",
                    ),
                    "review",
                )
        with pytest.raises(ForkRejected, match="unsupported_capability"):
            service.cancel(result.root_run_id)
        with pytest.raises(ForkRejected, match="unsupported_capability"):
            service.fork(
                result.root_run_id,
                ForkRequest(
                    source_checkpoint_id=original.checkpoints[0].checkpoint_id, patch={"top_k": 3}
                ),
                "fork",
            )
    with SQLitePackageStore(database) as store:
        assert store.get_view(result.root_run_id) == original
    assert not checkpoint_path(database).exists()


def artifact_package(view, *, secret=False):
    content = (
        '{"api_key":"offline-secret"}'
        if secret
        else '{"note":"offline unit-test receipt; not a real bill"}'
    )
    import hashlib

    metadata = Artifact(
        artifact_id="receipt",
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        media_type="application/json",
        created_at=datetime.now(UTC),
        source="offline test fixture",
        exportable=True,
    )
    value = observation_view(view, playback=False).model_dump(mode="json")
    value["spans"][0]["cost"] = {
        "kind": "actual",
        "amount": "0.01",
        "currency": "USD",
        "evidence_artifact_id": "receipt",
        "price_version": None,
    }
    record = PortableRun.model_validate(
        {
            "source": {
                "run_id": view.run.run_id,
                "mode": view.run.mode,
                "view_sha256": digest(view),
            },
            "view": value,
        }
    )
    return make_package(
        {
            f"runs/{view.run.run_id}.json": record.model_dump(mode="json"),
            "artifacts/receipt.json": PortableArtifact(
                metadata=metadata, content=content
            ).model_dump(mode="json"),
        },
        root_run_id=view.run.run_id,
        title="Explicit offline receipt fixture",
        kind="trace",
    ), content


def test_cost_evidence_keeps_content_and_provenance_with_fresh_local_artifact_identity(
    source, tmp_path
):
    _, a, _, _, _, _ = source
    package, content = artifact_package(a)
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        result, _ = store.import_data(canonical(package), "import")
        view = store.get_view(result.root_run_id)
        cost = view.spans[0].cost
        assert cost.kind == "actual" and cost.evidence_artifact_id != "receipt"
        assert store.read_artifact(cost.evidence_artifact_id) == content.encode()
        assert store.get_artifact(cost.evidence_artifact_id).source == "offline test fixture"
        assert store.provenance(result.root_run_id).claim == "unverified_source_record"
        assert store.import_data(canonical(package), "again") == (result, False)
        assert counts(database)["artifacts"] == 1


def test_credential_artifact_rejects_before_any_rows_or_blobs_are_created(source, tmp_path):
    _, a, _, _, _, _ = source
    package, _ = artifact_package(a, secret=True)
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        with pytest.raises(PackageRejected, match="artifact_contains_credentials"):
            store.import_data(canonical(package), "import")
        assert not any(counts(database).values())
        assert not store.artifact_root.exists()


@pytest.mark.parametrize("defect", ["span_owner", "checkpoint_owner", "parent_cycle"])
def test_invalid_snapshot_references_are_safe_rejections_before_mutation(source, tmp_path, defect):
    _, a, _, _, _, _ = source
    package = trace_package(a).model_dump(mode="json")
    record = package["files"][f"runs/{a.run.run_id}.json"]
    if defect == "span_owner":
        record["view"]["spans"][0]["run_id"] = "unknown"
    elif defect == "checkpoint_owner":
        record["view"]["checkpoints"][0]["run_id"] = "unknown"
    else:
        first, second = record["view"]["spans"][:2]
        first["parent_span_id"] = second["span_id"]
        second["parent_span_id"] = first["span_id"]
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        with pytest.raises(PackageRejected, match="package_invalid"):
            store.import_data(resign(package), "import")
        assert not any(counts(database).values())


def test_imported_records_are_append_only_at_the_database_boundary(source, tmp_path):
    _, _, _, _, _, package = source
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        result, _ = store.import_data(canonical(package), "import")
        for table in ("imports", "import_runs", "import_requests", "runs"):
            with pytest.raises(sqlite3.IntegrityError, match="append_only|read_only"):
                store._connection.execute(f"DELETE FROM {table}")
        for table, column in (
            ("imports", "source_sha256"),
            ("import_runs", "source_run_id"),
            ("import_requests", "fingerprint"),
            ("runs", "last_seq"),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append_only|read_only"):
                store._connection.execute(f"UPDATE {table} SET {column}={column}")
        event = store.events(result.root_run_id)[0]
        with pytest.raises(sqlite3.IntegrityError, match="imported_record_read_only"):
            store._connection.execute(
                "INSERT INTO events(event_id,run_id,seq,body) VALUES (?,?,?,?)",
                ("new-event", result.root_run_id, event.seq + 100, event.model_dump_json()),
            )


def test_http_import_no_credentials_replay_provenance_reexport_and_errors(
    source, tmp_path, monkeypatch
):
    _, a, _, _, _, package = source
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    database = tmp_path / "import.sqlite"
    with TestClient(create_app(database)) as client:
        client.app.state.service.model_factory = lambda _: pytest.fail("import invoked a model")
        headers = {"Content-Type": "application/json", "Idempotency-Key": "import"}
        response = client.post("/api/v1/imports", content=canonical(package), headers=headers)
        assert response.status_code == 201
        result = response.json()
        run_id = result["root_run_id"]
        assert client.get(response.headers["Location"]).json() == result
        again = client.post("/api/v1/imports", content=canonical(package), headers=headers)
        assert again.status_code == 200 and again.json() == result
        assert client.get(f"/api/v1/runs/{run_id}").json()["run"]["mode"] == "imported"
        assert client.get(f"/api/v1/runs/{run_id}/provenance").json()["source_mode"] == "synthetic"
        exported = client.get(f"/api/v1/runs/{run_id}/export")
        assert exported.status_code == 200 and exported.json() == package.model_dump(mode="json")
        events = client.get(f"/api/v1/runs/{run_id}/events")
        assert events.status_code == 200 and "event: run.created" in events.text
        assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 409
        assert (
            client.post(
                f"/api/v1/runs/{run_id}/evaluations", json={}, headers={"Idempotency-Key": "eval"}
            ).status_code
            == 409
        )
        assert client.get("/api/v1/imports/missing").status_code == 404
        assert client.get("/api/v1/runs/missing/provenance").status_code == 404
        assert (
            client.post(
                "/api/v1/imports",
                content=b"{}",
                headers={"Content-Type": "application/zip", "Idempotency-Key": "zip"},
            ).status_code
            == 415
        )
        malformed = client.post("/api/v1/imports", content=b'{"private-api-key":', headers=headers)
        assert malformed.status_code == 422 and malformed.json() == {"detail": "package_invalid"}
        assert (
            client.post(
                "/api/v1/imports", content=b" " * (MAX_PACKAGE_BYTES + 1), headers=headers
            ).status_code
            == 413
        )
        summary = client.post(
            "/api/v1/imports",
            content=canonical(trace_package(a, status="running")),
            headers={**headers, "Idempotency-Key": "summary"},
        )
        summary_id = summary.json()["root_run_id"]
        rejected = client.get(f"/api/v1/runs/{summary_id}/events")
        assert rejected.status_code == 409 and rejected.json()["detail"] == "unsupported_capability"
        assert client.get(f"/api/v1/runs/{summary_id}/provenance").json()["context"] is None
        assert (
            client.get(
                f"/api/v1/experiments/document-missing/export?run_id={summary_id}"
            ).status_code
            == 404
        )
    assert not checkpoint_path(database).exists()


def test_v3_migration_preserves_native_events_evaluations_and_request_identity(source):
    database, a, b, evaluation, review, _ = source
    with SQLitePackageStore(database) as store:
        events = store.events(b.run.run_id)
    with sqlite3.connect(database) as connection:
        for trigger in (
            "imported_runs_no_update",
            "imported_runs_no_delete",
            "imported_events_no_insert",
        ):
            connection.execute(f"DROP TRIGGER {trigger}")
        for table in ("import_requests", "import_runs", "imports"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version=3")
    with SQLitePackageStore(database) as store:
        assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert store.get_view(a.run.run_id) == a and store.get_view(b.run.run_id) == b
        assert store.events(b.run.run_id) == events
        assert store.get_evaluation(b.run.run_id, evaluation.evaluation_id) == evaluation
        assert store.get_review(b.run.run_id, review.review_id) == review
        assert store.create_evaluation(b.run.run_id, EvaluationRequest(), "eval") == (
            evaluation,
            False,
        )
        result, _ = store.import_data(canonical(export_run(database, b.run.run_id)), "import")
        assert len(result.runs) == 2


def test_timeout_experiment_round_trip_preserves_attempts_unknowns_and_fork_prefix(tmp_path):
    source_db, target = tmp_path / "source.sqlite", tmp_path / "import.sqlite"
    a, b = finished_pair(source_db, document=False)
    package = export_run(source_db, b.run.run_id)
    with SQLitePackageStore(target) as store:
        result, _ = store.import_data(canonical(package), "import")
        child = store.get_view(result.root_run_id)
        parent = store.get_view(child.run.parent_run_id)
        assert child.run.inherited_span_ids == (parent.spans[0].span_id,)
        assert [s.attempt for s in child.spans if s.kind == "tool"] == [1, 2]
        assert child.run.config.case is None  # Export context does not backfill source facts.
        assert store.provenance(child.run.run_id).context.experiment.ref.id == "tool-timeout"
        assert child.run.status == b.run.status and parent.run.status == a.run.status
        assert project_events(store.events(child.run.run_id)) == child
        assert all(
            s.usage == old.usage and s.cost == old.cost
            for s, old in zip(child.spans, b.spans, strict=True)
        )
    assert export_run(target, result.root_run_id) == package
    assert not checkpoint_path(target).exists()


def test_rollback_does_not_leave_imported_cost_metadata_or_available_artifacts(source, tmp_path):
    _, a, _, _, _, _ = source
    package, _ = artifact_package(a)
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        store._connection.execute(
            "CREATE TRIGGER fail_final_import BEFORE INSERT ON import_requests "
            "BEGIN SELECT RAISE(ABORT, 'offline rollback after blob'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="offline rollback"):
            store.import_data(canonical(package), "import")
        assert not any(counts(database).values())
        store._connection.execute("DROP TRIGGER fail_final_import")
        result, created = store.import_data(canonical(package), "import")
        assert created and store.get_view(result.root_run_id).spans[0].cost.kind == "actual"
        assert counts(database)["artifacts"] == 1


def test_source_evaluation_cannot_reference_an_absent_span(source, tmp_path):
    _, _, b, _, _, package = source
    data = package.model_dump(mode="json")
    data["files"][f"runs/{b.run.run_id}.json"]["evaluations"][0]["checks"][0]["span_ids"] = [
        "absent"
    ]
    database = tmp_path / "import.sqlite"
    with SQLitePackageStore(database) as store:
        with pytest.raises(PackageRejected, match="package_invalid"):
            store.import_data(resign(data), "import")
        assert not any(counts(database).values())
