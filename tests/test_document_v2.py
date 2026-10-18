"""The v2 protocol accepts batches; every actual tool remains a serial graph step."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event

import httpx
import pytest
from openai import OpenAI
from test_forks import saver_rows

import agenttinker.m0.openai_model as sdk_module
from agenttinker.core.projection import project_events
from agenttinker.core.requests import request_identity
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.document_model import DocumentBatchSyntheticModel
from agenttinker.experiments.evaluation import evaluate_documents
from agenttinker.experiments.reference import capture_document, package_reference
from agenttinker.packages.exporting import export_run
from agenttinker.packages.models import canonical
from agenttinker.packages.portable import parse_package
from agenttinker.runtime.checkpoints import CheckpointUnavailable, open_checkpoints
from agenttinker.runtime.document import DocumentExecutor
from agenttinker.runtime.document_v2 import DocumentV2Executor
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunService
from agenttinker.storage.packages import SQLitePackageStore
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore


class MeteredBatch(DocumentBatchSyntheticModel):
    def complete(self, messages):
        reply = super().complete(messages)
        reply.usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
        return reply


def create(service, *, version="2", variant="baseline", key="A"):
    view, _ = service.submit_document(
        DocumentRunRequest(mode="synthetic", agent_version=version, variant=variant), key
    )
    return service.wait(view.run.run_id)


def fork_request(view, top_k=3):
    return ForkRequest(
        source_checkpoint_id=view.checkpoints[0].checkpoint_id, patch={"top_k": top_k}
    )


def models(view):
    return [span for span in view.spans if span.kind == "model"]


def tools(view):
    return [span for span in view.spans if span.kind == "tool"]


def test_batch_restart_fork_and_continuous_fork_preserve_prefix_and_all_old_facts(tmp_path):
    database = tmp_path / "runs.sqlite"
    with RunService(database) as service:
        a = create(service)
        assert a.run.status == "succeeded" and a.run.config.agent == corpus.AGENT_V2
        assert a.run.config.experiment == corpus.EXPERIMENT_V2
        assert a.run.config.prompt_version == corpus.PROMPT_VERSION_V2
        assert len(models(a)) == 3 and len(tools(a)) == len(a.checkpoints) == 3
        assert len(models(a)[1].output["message"]["tool_calls"]) == 2
        assert [c.verdict for c in evaluate_documents(a).checks] == ["fail", "fail", "pass"]
        assert [c.available for c in service.checkpoint_availability(a.run.run_id)] == [
            True,
            False,
            False,
        ]
    before = saver_rows(database)
    with SQLiteEventStore(database) as store:
        events = store.events(a.run.run_id)
    with RunService(database) as service:
        b, _ = service.fork(a.run.run_id, fork_request(a), "B")
        b = service.wait(b.run.run_id)
        assert b.run.status == "succeeded"
        assert len(models(b)) == 2 and len(tools(b)) == len(b.checkpoints) == 4
        assert b.run.inherited_span_ids == (models(a)[0].span_id,)
        assert tools(b)[0].input["tool_call"] == tools(a)[0].input["tool_call"]
        assert [c.verdict for c in evaluate_documents(b, (models(a)[0],)).checks] == ["pass"] * 3
        reads = [s for s in tools(b) if s.logical_node_id == "read_document"]
        assert len({s.parent_span_id for s in reads}) == 1
        assert [s.call_index for s in reads] == [1, 2, 3]
        assert all(
            left.ended_at <= right.started_at
            for left, right in zip(reads[:-1], reads[1:], strict=True)
        )
        c, _ = service.fork(b.run.run_id, fork_request(b, 2), "C")
        assert service.wait(c.run.run_id).run.status == "succeeded"
        assert service.get(a.run.run_id) == a and service.get(b.run.run_id) == b
        assert all(s.usage.total_tokens is None and s.cost.kind == "unknown" for s in b.spans)
    after = saver_rows(database)
    old_ids = {row[2] for row in before["checkpoints"]}
    for table in before:
        assert [row for row in after[table] if row[2] in old_ids] == before[table]
    with SQLiteEventStore(database) as store:
        assert store.events(a.run.run_id) == events
        assert project_events(store.events(b.run.run_id)) == b


def test_v1_keeps_single_call_rejection_and_exact_old_idempotency_fingerprint(tmp_path):
    database = tmp_path / "runs.sqlite"
    with RunService(database, model_factory=lambda _: MeteredBatch()) as service:
        a = create(service, version="1")
        assert a.run.status == "failed" and len(tools(a)) == 1
        assert len(models(a)) == 2 and sum(s.usage.total_tokens for s in models(a)) == 24
        old_body = {"mode": "synthetic", "provider": None, "model": None, "variant": "baseline"}
        fingerprint = request_identity(
            "A",
            {
                "operation": "document-experiment",
                "experiment": corpus.EXPERIMENT.model_dump(),
                "request": old_body,
            },
        )
        with SQLiteEventStore(database) as store:
            assert store.request_run("A", fingerprint) == a
        assert service.submit_document(DocumentRunRequest(mode="synthetic"), "A") == (a, False)
        with pytest.raises(EventConflict):
            service.submit_document(DocumentRunRequest(mode="synthetic", agent_version="2"), "A")
        b = create(service, key="v2")
        assert b.run.status == "succeeded" and len(tools(b)) == 3
        with open_checkpoints(database) as saver:
            with pytest.raises(CheckpointUnavailable, match="runtime_incompatible"):
                DocumentExecutor.load_checkpoint(saver, b, b.checkpoints[0])
            with pytest.raises(CheckpointUnavailable, match="runtime_incompatible"):
                DocumentV2Executor.load_checkpoint(saver, a, a.checkpoints[0])
    with RunService(
        database, model_factory=lambda _: pytest.fail("idempotent read dispatched")
    ) as service:
        assert service.submit_document(DocumentRunRequest(mode="synthetic"), "A") == (a, False)


@pytest.mark.parametrize(
    "defect", ["duplicate_batch", "duplicate_past", "arguments", "index", "unknown_tool"]
)
def test_entire_batch_is_checked_before_any_of_its_tools_run(tmp_path, defect):
    class Invalid(MeteredBatch):
        def complete(self, messages):
            reply = super().complete(messages)
            if any(m["role"] == "tool" for m in messages):
                calls = reply.message["tool_calls"]
                if defect == "duplicate_batch":
                    calls[1]["id"] = calls[0]["id"]
                elif defect == "duplicate_past":
                    calls[1]["id"] = "document-tool-1"
                elif defect == "arguments":
                    calls[1]["function"]["arguments"] = '{"document_id":"release-v2","top_k":3}'
                elif defect == "index":
                    calls[1]["index"] = True
                else:
                    calls[1]["function"]["name"] = "unknown_tool"
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Invalid()) as service:
        view = create(service)
        assert view.run.status == "failed" and len(models(view)) == 2
        assert [s.logical_node_id for s in tools(view)] == ["search_documents"]
        assert len(view.checkpoints) == 1
        assert sum(s.usage.total_tokens for s in models(view)) == 24
        assert len(models(view)[-1].output["message"]["tool_calls"]) == 2


@pytest.mark.parametrize("initial", [False, True])
def test_batch_cannot_exceed_total_logical_tool_budget(tmp_path, initial):
    class OverBudget(MeteredBatch):
        def complete(self, messages):
            reply = super().complete(messages)
            has_tools = any(m["role"] == "tool" for m in messages)
            if initial or has_tools:
                template = reply.message["tool_calls"][0]
                reply.message["tool_calls"] = [
                    {**deepcopy(template), "id": f"over-{index}"}
                    for index in range(corpus.MAX_TOOL_CALLS + int(initial))
                ]
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: OverBudget()) as service:
        view = create(service)
        assert view.run.status == "failed"
        assert len(tools(view)) == (0 if initial else 1)
        with SQLiteEventStore(service.database) as store:
            assert store.events(view.run.run_id)[-1].data.reason == "tool_call_limit"


def test_model_and_tool_loops_remain_bounded_with_one_intent_batches(tmp_path):
    class Looping(MeteredBatch):
        def complete(self, messages):
            reply = super().complete(messages[:2])
            reply.message["tool_calls"][0]["id"] = f"loop-{len(messages)}"
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Looping()) as service:
        view = create(service)
        assert view.run.status == "failed"
        assert len(models(view)) == corpus.MAX_MODEL_CALLS
        assert len(tools(view)) == corpus.MAX_TOOL_CALLS


def test_cancel_during_first_read_keeps_result_without_executing_the_rest(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    original = corpus.read_document

    def gated(document_id, available):
        entered.set()
        assert release.wait(5)
        return original(document_id, available)

    monkeypatch.setattr(corpus, "read_document", gated)
    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: MeteredBatch()) as service:
        try:
            pending, _ = service.submit_document(
                DocumentRunRequest(mode="synthetic", agent_version="2"), "A"
            )
            assert entered.wait(3)
            service.cancel(pending.run.run_id)
        finally:
            release.set()
        view = service.wait(pending.run.run_id)
        assert view.run.status == "cancelled" and len(tools(view)) == 2
        assert tools(view)[-1].status == "succeeded" and "document" in tools(view)[-1].output
        assert len(models(view)) == 2 and sum(s.usage.total_tokens for s in models(view)) == 24
        assert len(models(view)[-1].output["message"]["tool_calls"]) == 2


def test_failed_middle_tool_preserves_intents_without_executing_remaining_tools(
    tmp_path, monkeypatch
):
    original = corpus.read_document

    def fail_middle(document_id, available):
        if document_id == "release-v2":
            raise RuntimeError("fixture exception must not leak")
        return original(document_id, available)

    monkeypatch.setattr(corpus, "read_document", fail_middle)
    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: MeteredBatch()) as service:
        view = create(service, variant="candidate")
        assert view.run.status == "failed" and len(tools(view)) == 3
        assert (
            tools(view)[-1].status == "failed"
            and tools(view)[-1].output["error_code"] == "RuntimeError"
        )
        assert len(models(view)) == 2
        assert len(models(view)[-1].output["message"]["tool_calls"]) == 3
        assert "fixture exception must not leak" not in view.model_dump_json()


def test_each_read_still_requires_a_returned_id(tmp_path):
    class Unavailable(MeteredBatch):
        def complete(self, messages):
            reply = super().complete(messages)
            if any(m["role"] == "tool" for m in messages):
                reply.message["tool_calls"][0]["function"]["arguments"] = (
                    '{"document_id":"release-v2-fix"}'
                )
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Unavailable()) as service:
        view = create(service)
        assert view.run.status == "failed" and len(tools(view)) == 2
        assert tools(view)[-1].output["error_code"] == "document_not_available"
        assert "document" not in tools(view)[-1].output


def test_fork_preserves_every_intent_when_first_response_contains_search_and_read(tmp_path):
    class Preplanned(DocumentBatchSyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages)
            if not any(m["role"] == "tool" for m in messages):
                reply.message["tool_calls"].append(
                    {
                        "id": "preplanned-read",
                        "type": "function",
                        "function": {
                            "name": "read_document",
                            "arguments": '{"document_id":"release-v2"}',
                        },
                    }
                )
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Preplanned()) as service:
        a = create(service)
        snapshot = service.resolve_checkpoint(a.run.run_id, a.checkpoints[0].checkpoint_id)
        pending = deepcopy(snapshot.values["pending_calls"])
        assert len(pending) == 2
        b, _ = service.fork(a.run.run_id, fork_request(a), "B")
        b = service.wait(b.run.run_id)
        assert b.run.status == "succeeded"
        assert [s.input["tool_call"] for s in tools(b)[:2]] == pending
        assert tools(b)[1].parent_span_id == models(a)[0].span_id


def test_concurrent_batch_branches_follow_their_own_search_results(tmp_path):
    barrier = Barrier(2)

    class Concurrent(DocumentBatchSyntheticModel):
        def complete(self, messages):
            if len([m for m in messages if m["role"] == "tool"]) == 1:
                barrier.wait(timeout=5)
            return super().complete(messages)

    with RunService(tmp_path / "runs.sqlite") as service:
        a = create(service)
        service.model_factory = lambda _: Concurrent()
        with ThreadPoolExecutor(2) as pool:
            branches = list(
                pool.map(
                    lambda k: service.fork(a.run.run_id, fork_request(a, k), f"B{k}")[0], (1, 3)
                )
            )
        for k, pending in zip((1, 3), branches, strict=True):
            view = service.wait(pending.run.run_id)
            assert view.run.status == "succeeded"
            assert len([s for s in tools(view) if s.logical_node_id == "read_document"]) == k
            snapshot = service.resolve_checkpoint(
                view.run.run_id, view.checkpoints[0].checkpoint_id
            )
            assert snapshot.values["run_id"] == view.run.run_id
        assert service.get(a.run.run_id) == a


@pytest.mark.parametrize("tamper", ["queue", "queue_and_message", "system_prompt"])
def test_queue_checkpoint_is_bound_to_original_model_observation(tmp_path, monkeypatch, tamper):
    with RunService(tmp_path / "runs.sqlite") as service:
        view = create(service)
        reference = view.checkpoints[0]
        snapshot = service.resolve_checkpoint(view.run.run_id, reference.checkpoint_id)
        values = deepcopy(snapshot.values)
        if tamper == "system_prompt":
            values["messages"][0]["content"] += " changed"
        else:
            values["pending_calls"][0]["function"]["arguments"] = '{"query":"changed"}'
            values["tool_call"] = deepcopy(values["pending_calls"][0])
            if tamper == "queue_and_message":
                values["messages"][-1]["tool_calls"] = deepcopy(values["pending_calls"])
        altered = snapshot._replace(values=values)

        class AlteredGraph:
            def get_state(self, _):
                return altered

        monkeypatch.setattr(
            DocumentV2Executor, "graph", classmethod(lambda *_args, **_kwargs: AlteredGraph())
        )
        with open_checkpoints(service.database) as saver:
            with pytest.raises(CheckpointUnavailable, match="checkpoint_state_invalid"):
                DocumentV2Executor.load_checkpoint(saver, view, reference)


def test_v2_reference_evaluation_and_package_round_trip_are_read_only(tmp_path):
    database = tmp_path / "native.sqlite"
    report = capture_document(database, DocumentRunRequest(mode="synthetic", agent_version="2"))
    assert all(report["checks"].values()) and not report["real_reference_verified"]
    package = package_reference(report)
    assert package.files["context.json"]["agent"]["ref"] == corpus.AGENT_V2.model_dump()
    parse_package(canonical(package))
    with SQLitePackageStore(tmp_path / "imported.sqlite") as store:
        result, created = store.import_data(canonical(package), "import")
        assert created
        for link in result.runs:
            view = store.get_view(link.local_run_id)
            assert view.run.mode == "imported" and not view.run.capabilities.fork_from_checkpoint
    exported = export_run(database, report["runs"]["B"]["run"]["run_id"])
    for path, record in package.files.items():
        if path.startswith("runs/"):
            assert exported.files[path] == record


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_official_sdk_batch_round_trip_preserves_ids_usage_and_sends_all_results_together(
    tmp_path, monkeypatch, provider
):
    requests, clients = [], []
    driver = DocumentBatchSyntheticModel()
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "offline-placeholder")
    monkeypatch.setenv(f"{provider.upper()}_MODEL", "offline-model")

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        reply = driver.complete(body["messages"])
        for index, call in enumerate(reply.message.get("tool_calls", [])):
            call["index"] = index
        return httpx.Response(
            200,
            json={
                "id": f"offline-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-model",
                "choices": [
                    {"index": 0, "message": reply.message, "finish_reason": reply.finish_reason}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    def client_factory(**kwargs):
        client = OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        clients.append(client)
        return client

    monkeypatch.setattr(sdk_module, "OpenAI", client_factory)
    with RunService(tmp_path / "runs.sqlite") as service:
        pending, _ = service.submit_document(
            DocumentRunRequest(mode="live", provider=provider, agent_version="2"), "A"
        )
        a = service.wait(pending.run.run_id)
        b, _ = service.fork(a.run.run_id, fork_request(a), "B")
        b = service.wait(b.run.run_id)
        assert a.run.status == b.run.status == "succeeded" and len(requests) == 5
        assert sum(s.usage.total_tokens for s in models(a)) == 36
        assert sum(s.usage.total_tokens for s in models(b)) == 24
        assert [call["index"] for call in models(b)[0].output["message"]["tool_calls"]] == [0, 1, 2]
        for body in requests:
            assert body["tool_choice"] == "auto"
            for index, message in enumerate(body["messages"]):
                calls = message.get("tool_calls", [])
                assert all("index" not in call for call in calls)
                if calls:
                    results = body["messages"][index + 1 : index + 1 + len(calls)]
                    assert [item["tool_call_id"] for item in results] == [
                        call["id"] for call in calls
                    ]
        assert service.get(a.run.run_id) == a
    assert all(client.is_closed() for client in clients)
