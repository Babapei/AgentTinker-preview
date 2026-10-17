from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_forks import saver_rows

from agenttinker.api.app import create_app
from agenttinker.core.records import Run
from agenttinker.experiments.evaluation import EvaluationRequest, ReviewRequest
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.packages.exporting import export_run, make_package
from agenttinker.packages.models import (
    MAX_PACKAGE_BYTES,
    PackageRejected,
    PortableRun,
    RecordSource,
    canonical,
    digest,
)
from agenttinker.packages.portable import inspect_package, observation_view, parse_package
from agenttinker.runtime.checkpoints import checkpoint_path
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunRequest, RunService
from agenttinker.storage.evaluations import SQLiteEvaluationStore


def finished_pair(database, *, document=True):
    with RunService(database) as service:
        a, _ = (
            service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
            if document
            else service.submit(RunRequest(mode="synthetic"), "A")
        )
        a = service.wait(a.run.run_id)
        b, _ = service.fork(
            a.run.run_id,
            ForkRequest(
                source_checkpoint_id=a.checkpoints[0].checkpoint_id,
                patch={"top_k": 3} if document else {"tool_retry_limit": 1},
            ),
            "B",
        )
        return a, service.wait(b.run.run_id)


def resign(data):
    for entry in data["manifest"]["entries"]:
        value = data["files"][entry["path"]]
        entry.update(sha256=digest(value), size_bytes=len(canonical(value)))
    return canonical(data)


@pytest.mark.parametrize("document", [True, False], ids=["document", "timeout"])
def test_export_both_experiments_preserves_native_history_and_excludes_runtime_state(
    tmp_path, document
):
    database = tmp_path / "runs.sqlite"
    a, b = finished_pair(database, document=document)
    original_states = saver_rows(database)
    with SQLiteEvaluationStore(database) as store:
        events = {view.run.run_id: store.events(view.run.run_id) for view in (a, b)}
    package = export_run(database, b.run.run_id)
    assert parse_package(canonical(package)) == package
    context, records, artifacts = inspect_package(package)
    assert context.experiment.ref.id == ("document-missing" if document else "tool-timeout")
    assert context.case.task == b.run.config.task and not artifacts
    assert list(records) == [a.run.run_id, b.run.run_id]
    for view in (a, b):
        record = records[view.run.run_id]
        assert record.source.view_sha256 == digest(view)
        assert record.view.spans == view.spans
        assert record.view.run.mode == "synthetic"
        assert not record.view.run.capabilities.fork_from_checkpoint
        assert all(not cp.locator and not cp.allowed_patch_fields for cp in record.view.checkpoints)
    assert "sqlite-v1" not in canonical(package).decode()
    assert saver_rows(database) == original_states
    with SQLiteEvaluationStore(database) as store:
        assert store.get_view(a.run.run_id) == a and store.get_view(b.run.run_id) == b
        assert all(store.events(key) == value for key, value in events.items())
    if not document:
        assert b.run.config.case is None and context.case.ref.id.startswith("timeout-task-")
        assert context.notes  # Reconstructed context is declared, never written back into Run.


def test_export_evaluations_keep_source_and_portable_evidence_hashes_distinct(tmp_path):
    database = tmp_path / "runs.sqlite"
    a, b = finished_pair(database)
    with SQLiteEvaluationStore(database) as store:
        result, _ = store.create_evaluation(b.run.run_id, EvaluationRequest(), "eval")
        review, _ = store.create_review(
            b.run.run_id,
            ReviewRequest(
                evaluation_id=result.evaluation_id,
                input_hash=result.input_hash,
                reviewer="offline fixture",
                fact_coverage={"configurable-retries": "covered", "citation-fix": "covered"},
                judgement="uncertain",
                explanation="离线导出契约测试，不是真实人工评价。",
            ),
            "review",
        )
    checkpoint_path(database).unlink()  # Export requires no saver or provider configuration.
    package = export_run(database, b.run.run_id)
    _, records, _ = inspect_package(package)
    record = records[b.run.run_id]
    assert record.evaluations == (result,) and record.reviews == (review,)
    binding = record.evaluation_bindings[0]
    assert binding.source_input_hash == result.input_hash
    assert binding.portable_input_hash != binding.source_input_hash
    assert parse_package(canonical(package)) == package
    assert not checkpoint_path(database).exists()


def test_export_redacts_recognized_credential_fields_without_modifying_original(tmp_path):
    class EchoCredentials(SyntheticModel):
        def complete(self, messages):
            result = super().complete(messages)
            result.raw_response = {
                "headers": {"Authorization": "offline-secret"},
                "api_key": "offline-secret",
            }
            return result

    database = tmp_path / "runs.sqlite"
    with RunService(database, model_factory=lambda _: EchoCredentials()) as service:
        view, _ = service.submit(RunRequest(mode="synthetic", inject_timeout=False), "A")
        view = service.wait(view.run.run_id)
    assert "offline-secret" in view.model_dump_json()
    package = export_run(database, view.run.run_id)
    assert b"offline-secret" not in canonical(package) and b"[REDACTED]" in canonical(package)
    with SQLiteEvaluationStore(database) as store:
        assert store.get_view(view.run.run_id) == view


def test_normalized_trace_can_be_inspected_without_fabricating_an_event_log(tmp_path):
    a, _ = finished_pair(tmp_path / "runs.sqlite", document=False)
    snapshot = observation_view(a, playback=False)
    record = PortableRun(
        source=RecordSource(run_id=a.run.run_id, mode=a.run.mode, view_sha256=digest(a)),
        view=snapshot,
    )
    package = make_package(
        {f"runs/{a.run.run_id}.json": record.model_dump(mode="json")},
        root_run_id=a.run.run_id,
        title="Normalized external trace",
        kind="trace",
    )
    _, records, _ = inspect_package(parse_package(canonical(package)))
    assert records[a.run.run_id].events is None
    assert not records[a.run.run_id].view.run.capabilities.record_playback


@pytest.mark.parametrize(
    "defect",
    ["path", "media", "version", "hash", "missing_parent", "projection", "fixture", "evaluator"],
)
def test_invalid_packages_are_rejected_before_any_mutation(tmp_path, defect):
    database = tmp_path / "runs.sqlite"
    a, b = finished_pair(database)
    package = export_run(database, b.run.run_id)
    data = package.model_dump(mode="json")
    if defect == "path":
        data["manifest"]["entries"][0]["path"] = "../outside.py"
    elif defect == "media":
        data["manifest"]["entries"][0]["media_type"] = "application/x-python"
    elif defect == "version":
        data["format_version"] = "future"
    elif defect == "hash":
        data["files"][f"runs/{b.run.run_id}.json"]["source"]["claim"] = "forged"
    elif defect == "missing_parent":
        data["files"].pop(f"runs/{a.run.run_id}.json")
        data["manifest"]["entries"] = [
            e for e in data["manifest"]["entries"] if e["path"] != f"runs/{a.run.run_id}.json"
        ]
    elif defect == "projection":
        data["files"][f"runs/{b.run.run_id}.json"]["events"].pop()
    elif defect == "fixture":
        data["files"]["context.json"]["fixture"]["documents"][0]["text"] = "changed"
    else:
        data["files"]["context.json"]["evaluators"][0]["ref"]["id"] = "install-and-execute"
    encoded = canonical(data) if defect in {"path", "media", "version", "hash"} else resign(data)
    with pytest.raises(PackageRejected, match="package_invalid"):
        parse_package(encoded)
    with SQLiteEvaluationStore(database) as store:
        assert store.get_view(b.run.run_id) == b


@pytest.mark.parametrize(
    "data",
    [b'{"format":"a","format":"b"}', b'{"x":NaN}', b"PK\x03\x04not-a-json-package", b'{"bad":'],
)
def test_strict_package_json_rejects_duplicate_keys_non_finite_and_archive_data(data):
    with pytest.raises(PackageRejected, match="package_invalid"):
        parse_package(data)


def test_package_bytes_are_bounded_before_json_parsing():
    with pytest.raises(PackageRejected, match="package_too_large"):
        parse_package(b" " * (MAX_PACKAGE_BYTES + 1))


def test_http_export_is_read_only_without_credentials_and_rejects_active_runs(
    tmp_path, monkeypatch
):
    database = tmp_path / "runs.sqlite"
    a, b = finished_pair(database)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(database)
    with TestClient(app) as client:
        app.state.service.model_factory = lambda _: pytest.fail("export dispatched a model")
        response = client.get(f"/api/v1/runs/{b.run.run_id}/export")
        assert (
            response.status_code == 200 and "attachment" in response.headers["content-disposition"]
        )
        assert parse_package(response.content).manifest.root_run_id == b.run.run_id
        assert (
            client.get(
                f"/api/v1/experiments/document-missing/export?run_id={b.run.run_id}"
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/experiments/missing/export?run_id={b.run.run_id}").status_code
            == 404
        )
        now = datetime.now(UTC)
        queued = Run(
            run_id="queued-export",
            mode="synthetic",
            config=a.run.config,
            created_at=now,
            updated_at=now,
        )
        with SQLiteEvaluationStore(database) as store:
            store.create_requested_run(queued, "queued-export", "fixture")
        rejected = client.get("/api/v1/runs/queued-export/export")
        assert rejected.status_code == 409 and rejected.json()["detail"] == "package_run_active"
        assert client.get(f"/api/v1/runs/{b.run.run_id}").json() == b.model_dump(mode="json")
