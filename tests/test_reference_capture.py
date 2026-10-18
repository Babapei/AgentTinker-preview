"""Reference recording is explicit; packaging and checking never replay execution."""

import json
import runpy
from functools import partial
from pathlib import Path

import pytest

from agenttinker.experiments import documents as corpus
from agenttinker.experiments.document_model import DocumentSyntheticModel
from agenttinker.experiments.reference import capture_document, document_checks, package_reference
from agenttinker.m0.models import ModelOutput
from agenttinker.packages.exporting import export_run
from agenttinker.packages.models import canonical
from agenttinker.packages.portable import inspect_package, parse_package
from agenttinker.runtime.checkpoints import checkpoint_path
from agenttinker.runtime.service import DocumentRunRequest, RunService
from agenttinker.storage.packages import SQLitePackageStore
from agenttinker.storage.sqlite import EventConflict


@pytest.fixture
def reference(tmp_path):
    database = tmp_path / "native.sqlite"
    return database, capture_document(database, DocumentRunRequest(mode="synthetic"))


def denied(_):
    pytest.fail("observation operation constructed a model")


def test_capture_evidence_is_separate_from_semantics_usage_and_live_claims(reference):
    database, report = reference
    assert report["created_now"] == {"A": True, "B": True}
    assert all(report["checks"].values()) and all(document_checks(report).values())
    assert not report["real_reference_verified"]
    assert report["measurements"]["A"]["new_model_calls"] == 4
    assert report["measurements"]["B"]["new_model_calls"] == 4
    assert all(row["new_total_tokens"] is None for row in report["measurements"].values())
    assert (
        report["source_runtime_rows_sha256"]["before"]
        == report["source_runtime_rows_sha256"]["after"]
    )
    assert all(e["answer_review"] == "unreviewed" for e in report["evaluations"].values())
    with SQLitePackageStore(database) as store:
        assert all(
            store.reviews(view["run"]["run_id"]).total == 0 for view in report["runs"].values()
        )


def test_reopened_capture_reuses_both_requests_and_evaluations_without_model_construction(
    reference,
):
    database, original = reference
    repeated = capture_document(
        database,
        DocumentRunRequest(mode="synthetic"),
        service_factory=partial(RunService, model_factory=denied),
    )
    assert repeated["created_now"] == {"A": False, "B": False}
    assert all(repeated["checks"].values())
    for key in ("runs", "events", "evaluations", "measurements"):
        assert repeated[key] == original[key]
    with pytest.raises(EventConflict, match="idempotency_key_payload_conflict"):
        capture_document(database, DocumentRunRequest(mode="synthetic", variant="candidate"))


@pytest.mark.parametrize("invalid_protocol", [False, True])
def test_missing_search_boundary_stops_without_branch_or_false_success(tmp_path, invalid_protocol):
    class Direct(DocumentSyntheticModel):
        provider = "synthetic"

        def complete(self, messages):
            return ModelOutput(
                provider="synthetic",
                model="offline-direct",
                request={"messages": messages},
                message={"role": "assistant", "content": "材料不足。"},
                choice_count=0 if invalid_protocol else 1,
                finish_reason="stop",
            )

    report = capture_document(
        tmp_path / "native.sqlite",
        DocumentRunRequest(mode="synthetic"),
        service_factory=partial(RunService, model_factory=lambda _: Direct()),
    )
    assert report["checks"] == {"baseline_has_first_search_boundary": False}
    assert set(report["runs"]) == {"A"} and report["created_now"]["B"] is False
    assert report["runs"]["A"]["run"]["status"] == ("failed" if invalid_protocol else "succeeded")
    assert len(report["events"]["A"]) > 0 and not report["real_reference_verified"]
    with pytest.raises(ValueError, match="reference_pair_incomplete"):
        package_reference(report)


def test_candidate_missing_citation_is_an_observed_failure_without_changing_execution_status(
    tmp_path,
):
    class InvalidCitation(DocumentSyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages)
            if not reply.message.get("tool_calls"):
                reply.message["content"] = "Unknown source [not-returned]."
            return reply

    report = capture_document(
        tmp_path / "native.sqlite",
        DocumentRunRequest(mode="synthetic"),
        service_factory=partial(RunService, model_factory=lambda _: InvalidCitation()),
    )
    assert report["checks"]["both_executions_succeeded"]
    assert report["checks"]["candidate_material_returned_and_read"]
    assert not report["checks"]["candidate_citations_reference_read_sources"]
    assert report["checks"]["source_observations_unchanged"]
    with pytest.raises(ValueError, match="reference_checks_failed"):
        package_reference(report)
    package = package_reference(report, include_observed_failure=True)
    context, records, _ = inspect_package(package)
    assert "未全部满足" in context.notes[-1]
    child = records[report["runs"]["B"]["run"]["run_id"]]
    assert child.evaluations[0].checks[-1].verdict == "fail"
    assert child.view.run.status == "succeeded"


def test_packaging_reproduces_production_export_and_imports_without_sdk_saver_or_tools(
    reference, tmp_path, monkeypatch
):
    database, report = reference
    expected = export_run(database, report["runs"]["B"]["run"]["run_id"])
    checkpoint_path(database).unlink()
    monkeypatch.setattr(corpus, "search_documents", denied)
    monkeypatch.setattr(corpus, "read_document", denied)
    package = package_reference(report)
    assert parse_package(canonical(package)) == package
    assert package.files == expected.files
    assert (
        package_reference(report) == package
    )  # Frozen capture time, deterministic file/hash output.
    _, records, _ = inspect_package(package)
    assert all(not record.reviews for record in records.values())
    with SQLitePackageStore(tmp_path / "import.sqlite") as store:
        result, _ = store.import_data(canonical(package), "offline")
        assert store.provenance(result.root_run_id).source_mode == "synthetic"
    assert not checkpoint_path(database).exists()


def test_preexisting_real_timeout_reference_converts_without_new_execution(tmp_path, monkeypatch):
    reference = json.loads(Path("examples/m3/deepseek-timeout-live.json").read_text())
    monkeypatch.setattr(corpus, "search_documents", denied)
    package = package_reference(reference)
    context, records, _ = inspect_package(package)
    assert context.experiment.ref.id == "tool-timeout"
    assert all(record.source.mode == "live" for record in records.values())
    assert (
        sum(
            s.usage.total_tokens
            for record in records.values()
            for s in record.view.spans
            if s.kind == "model"
        )
        == 624
    )
    with SQLitePackageStore(tmp_path / "import.sqlite") as store:
        result, _ = store.import_data(canonical(package), "existing-real")
        assert len(result.runs) == 2
    assert not checkpoint_path(tmp_path / "import.sqlite").exists()


def test_declared_success_cannot_hide_a_tampered_rule_digest(reference):
    _, report = reference
    report["evaluations"]["B"]["input_hash"] = "0" * 64
    assert all(report["checks"].values())
    assert not document_checks(report)["rule_evidence_recomputed"]
    with pytest.raises(ValueError, match="reference_checks_failed"):
        package_reference(report)


def test_capture_cli_failure_preserves_prior_success_and_received_facts_without_raw_error(
    reference, tmp_path, monkeypatch, capsys
):
    database, report = reference
    output = tmp_path / "report.json"
    output.write_text("previous-success")
    main = runpy.run_path("scripts/capture_document_reference.py")["main"]

    def failed(*args, **kwargs):
        raise RuntimeError("private-error-marker")

    main.__globals__["capture_document"] = failed
    monkeypatch.setattr(
        "sys.argv",
        ["capture", "--mode", "synthetic", "--database", str(database), "--output", str(output)],
    )
    assert main() == 1 and output.read_text() == "previous-success"
    failure = json.loads(output.with_suffix(".failed.json").read_text())
    assert failure["error_code"] == "RuntimeError"
    assert set(failure["runs"]) == {view["run"]["run_id"] for view in report["runs"].values()}
    assert all(failure["events"].values())
    assert "private-error-marker" not in json.dumps(failure) + capsys.readouterr().out


@pytest.mark.parametrize("index", [-1, True, "0"])
def test_tool_transport_index_is_strict_and_cannot_change_execution_arguments(index):
    from agenttinker.experiments.document_model import validate_reply

    reply = DocumentSyntheticModel().complete([{"role": "user", "content": "offline"}])
    reply.message["tool_calls"][0]["index"] = index
    with pytest.raises(ValueError):
        validate_reply(reply, set())


def test_original_real_protocol_failure_is_preserved_and_its_index_is_now_accepted():
    from agenttinker.experiments.document_model import validate_reply

    report = json.loads(Path("examples/m4/deepseek-document-protocol-failure.json").read_text())
    view = report["runs"]["A"]
    assert view["run"]["status"] == "failed"
    assert report["measurements"]["A"]["new_total_tokens"] == 552
    assert report["checks"]["baseline_has_first_search_boundary"] is False
    reply = ModelOutput.model_validate(view["spans"][0]["output"])
    call = validate_reply(reply, set())
    assert call == reply.message["tool_calls"][0]
    assert call["index"] == 0 and call["function"]["name"] == "search_documents"
    assert len(view["spans"]) == 1 and not view["checkpoints"]


def test_explicit_failure_packaging_keeps_unmet_outcomes_but_never_bypasses_integrity(reference):
    _, report = reference
    report["checks"]["source_observations_unchanged"] = False
    with pytest.raises(ValueError, match="reference_checks_failed"):
        package_reference(report, include_observed_failure=True)
    report["checks"]["source_observations_unchanged"] = True
    report["evaluations"]["B"]["input_hash"] = "0" * 64
    with pytest.raises(ValueError, match="reference_checks_failed"):
        package_reference(report, include_observed_failure=True)


@pytest.mark.parametrize("filename", ["tool-timeout", "document-missing", "document-missing-v2"])
def test_distributed_reference_packages_validate_import_and_preserve_observed_failures(
    filename, tmp_path
):
    data = Path(f"examples/m4/{filename}.json").read_bytes()
    package = parse_package(data)
    _, records, _ = inspect_package(package)
    assert len(records) == 2 and all(r.source.mode == "live" for r in records.values())
    target = tmp_path / "read.sqlite"
    with SQLitePackageStore(target) as store:
        result, _ = store.import_data(data, filename)
        assert store.get_view(result.root_run_id).run.mode == "imported"
        if filename == "document-missing":
            child = records[package.manifest.root_run_id]
            assert child.view.run.status == "failed"
            assert [c.verdict for c in child.evaluations[0].checks] == ["pass", "fail", "unknown"]
            assert len(child.view.spans[-1].output["message"]["tool_calls"]) == 2
            assert child.view.spans[-1].usage.total_tokens == 695
            assert not child.reviews
            assert store.provenance(result.root_run_id).evaluations[0].answer_review == "unreviewed"
        elif filename == "document-missing-v2":
            child = records[package.manifest.root_run_id]
            assert (
                child.view.run.status == "succeeded" and child.view.run.config.agent.version == "2"
            )
            assert [c.verdict for c in child.evaluations[0].checks] == ["pass", "pass", "fail"]
            assert "hrelease-v2" in child.evaluations[0].cited_document_ids
            assert not child.reviews
    assert not checkpoint_path(target).exists()


def test_reference_checks_every_executed_intent_in_the_inherited_first_batch():
    report = json.loads(Path("examples/m4/deepseek-document-v2-live-observed.json").read_text())
    assert document_checks(report)["same_search_call_and_query"]
    b = report["runs"]["B"]
    prefix = b["run"]["inherited_span_ids"][0]
    tools = [
        span for span in b["spans"] if span["kind"] == "tool" and span["parent_span_id"] == prefix
    ]
    assert len(tools) == 2
    tools[1]["input"]["tool_call"]["function"]["arguments"] = '{"query":"changed-second-query"}'
    assert not document_checks(report)["same_search_call_and_query"]
