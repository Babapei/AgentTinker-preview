import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from test_api import sse_events
from test_forks import saver_rows

import agenttinker.m0.openai_model as sdk_module
from agenttinker.api.app import create_app
from agenttinker.core.projection import RunView, project_events
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.document_model import DocumentSyntheticModel
from agenttinker.experiments.evaluation import evaluate_documents
from agenttinker.runtime.checkpoints import ForkRejected, checkpoint_path
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunRequest, RunService
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore


def fork_request(view, top_k=3, checkpoint_index=0):
    return ForkRequest(
        source_checkpoint_id=view.checkpoints[checkpoint_index].checkpoint_id,
        patch={"top_k": top_k},
    )


def test_document_loop_restart_fork_preserves_original_and_evaluates_evidence(tmp_path):
    database = tmp_path / "runs.sqlite"
    with RunService(database) as service:
        a, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
        a = service.wait(a.run.run_id)
        assert a.run.status == "succeeded" and a.run.config.agent == corpus.AGENT
        assert len(a.spans) == 7 and len(a.checkpoints) == 3
        assert [c.verdict for c in evaluate_documents(a).checks] == ["fail", "fail", "pass"]
        assert [r.available for r in service.checkpoint_availability(a.run.run_id)] == [
            True,
            False,
            False,
        ]
        with pytest.raises(ForkRejected, match="unsupported_capability"):
            service.fork(a.run.run_id, fork_request(a, checkpoint_index=1), "read-boundary")
        with pytest.raises(ForkRejected, match="invalid_patch"):
            service.fork(
                a.run.run_id,
                ForkRequest(
                    source_checkpoint_id=a.checkpoints[0].checkpoint_id,
                    patch={"tool_retry_limit": 1},
                ),
                "wrong-variable",
            )
    old_states = saver_rows(database)
    with SQLiteEventStore(database) as store:
        old_events = store.events(a.run.run_id)
    with RunService(database) as service:
        b, _ = service.fork(a.run.run_id, fork_request(a), "B")
        b = service.wait(b.run.run_id)
        assert b.run.status == "succeeded" and len(b.spans) == 8
        assert b.run.inherited_span_ids == (a.spans[0].span_id,)
        assert b.run.config.variant.id == "document-top3"
        assert b.spans[0].input["tool_call"] == a.spans[1].input["tool_call"]
        assert b.spans[0].parent_span_id == a.spans[0].span_id
        assert [s.call_index for s in b.spans if s.kind == "model"] == [2, 3, 4, 5]
        assert [s.call_index for s in b.spans if s.logical_node_id == "read_document"] == [1, 2, 3]
        assert all(s.usage.total_tokens is None and s.cost.kind == "unknown" for s in b.spans)
        result = evaluate_documents(b, (a.spans[0],))
        assert [c.verdict for c in result.checks] == ["pass", "pass", "pass"]
        assert result.answer_review == "unreviewed"
        c, _ = service.fork(b.run.run_id, fork_request(b, 2), "C")
        c = service.wait(c.run.run_id)
        assert c.run.status == "succeeded" and c.run.inherited_span_ids == b.run.inherited_span_ids
        assert service.get(a.run.run_id) == a and service.get(b.run.run_id) == b
    new_states = saver_rows(database)
    old_ids = {row[2] for row in old_states["checkpoints"]}
    for table in old_states:
        assert [row for row in new_states[table] if row[2] in old_ids] == old_states[table]
    with SQLiteEventStore(database) as store:
        assert store.events(a.run.run_id) == old_events
        assert project_events(store.events(b.run.run_id)) == b


def test_concurrent_forks_follow_their_own_checkpoints_not_shared_thread_head(tmp_path):
    barrier = Barrier(2)

    class ConcurrentModel(DocumentSyntheticModel):
        def complete(self, messages):
            # Both branches must have executed their different search result before proceeding.
            if len([m for m in messages if m["role"] == "tool"]) == 1:
                barrier.wait(timeout=5)
            return super().complete(messages)

    with RunService(tmp_path / "runs.sqlite") as service:
        a, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
        a = service.wait(a.run.run_id)
        service.model_factory = lambda _: ConcurrentModel()
        with ThreadPoolExecutor(2) as pool:
            submitted = list(
                pool.map(
                    lambda k: service.fork(a.run.run_id, fork_request(a, k), f"B{k}"),
                    (1, 3),
                )
            )
        branches = [service.wait(view.run.run_id) for view, _ in submitted]
        for k, branch in zip((1, 3), branches, strict=True):
            assert branch.run.status == "succeeded"
            assert len(branch.spans[0].output["documents"]) == k
            assert len([s for s in branch.spans if s.logical_node_id == "read_document"]) == k
            snapshot = service.resolve_checkpoint(
                branch.run.run_id, branch.checkpoints[0].checkpoint_id
            )
            assert snapshot.values["run_id"] == branch.run.run_id
        assert service.get(a.run.run_id) == a


def test_document_identity_survives_restart_missing_saver_and_legacy_requests(tmp_path):
    database = tmp_path / "runs.sqlite"
    request = DocumentRunRequest(mode="synthetic")
    with RunService(database) as service:
        a, _ = service.submit_document(request, "A")
        a = service.wait(a.run.run_id)
        b, _ = service.fork(a.run.run_id, fork_request(a), "B")
        b = service.wait(b.run.run_id)
        with pytest.raises(EventConflict):
            service.submit(RunRequest(mode="synthetic"), "A")
    checkpoint_path(database).unlink()
    with RunService(database, model_factory=lambda _: pytest.fail("duplicate dispatch")) as service:
        assert service.submit_document(request, "A") == (a, False)
        assert service.fork(a.run.run_id, fork_request(a), "B") == (b, False)
        assert service.checkpoint_availability(a.run.run_id)[0].reason == "checkpoint_missing"
        assert not checkpoint_path(database).exists()


@pytest.mark.parametrize("defect", ["choices", "parallel", "executor_argument", "duplicate_id"])
def test_bad_protocol_preserves_returned_usage_without_executing_bad_tool(tmp_path, defect):
    class BadModel(DocumentSyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages)
            reply.usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
            if defect == "choices":
                reply.choice_count = 2
            elif defect == "parallel":
                reply.message["tool_calls"] *= 2
            elif defect == "executor_argument":
                reply.message["tool_calls"][0]["function"]["arguments"] = (
                    '{"query":"release","top_k":3}'
                )
            elif len(messages) > 2:
                reply.message["tool_calls"][0]["id"] = "document-tool-1"
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: BadModel()) as service:
        view, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
        view = service.wait(view.run.run_id)
        assert view.run.status == "failed"
        models = [s for s in view.spans if s.kind == "model"]
        assert len(models) == (2 if defect == "duplicate_id" else 1)
        assert all(s.status == "succeeded" and s.usage.total_tokens == 12 for s in models)
        assert len(view.checkpoints) == (1 if defect == "duplicate_id" else 0)


def test_model_autonomy_can_answer_without_forced_tools_and_loops_are_bounded(tmp_path):
    class AnswerOnly(DocumentSyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages)
            reply.message = {"role": "assistant", "content": "材料不足。"}
            reply.finish_reason = "stop"
            return reply

    class Looping(DocumentSyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages[:2])
            reply.message["tool_calls"][0]["id"] = f"call-{len(messages)}"
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: AnswerOnly()) as service:
        a, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "answer")
        a = service.wait(a.run.run_id)
        assert a.run.status == "succeeded" and len(a.spans) == 1 and not a.checkpoints
        assert [c.verdict for c in evaluate_documents(a).checks] == ["unknown"] * 3
        service.model_factory = lambda _: Looping()
        b, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "loop")
        b = service.wait(b.run.run_id)
        assert b.run.status == "failed"
        assert len([s for s in b.spans if s.kind == "model"]) == 8
        assert len([s for s in b.spans if s.kind == "tool"]) == 7


def test_reading_a_known_but_unreturned_document_fails_without_exposing_its_body(tmp_path):
    class Unavailable(DocumentSyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages)
            if len(messages) > 2:
                reply.message["tool_calls"][0]["function"]["arguments"] = (
                    '{"document_id":"release-v2-fix"}'
                )
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Unavailable()) as service:
        view, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
        view = service.wait(view.run.run_id)
        assert view.run.status == "failed"
        assert view.spans[-1].logical_node_id == "read_document"
        assert view.spans[-1].status == "failed" and "document" not in view.spans[-1].output
        assert view.spans[-1].output["error_code"] == "document_not_available"
        result = evaluate_documents(view)
        assert result.read_document_ids == ()
        assert result.checks[-1].verdict == "unknown"


def test_cancel_inflight_document_model_keeps_returned_usage_and_does_not_start_tool(tmp_path):
    entered, release = Event(), Event()

    class Gated(DocumentSyntheticModel):
        def complete(self, messages):
            entered.set()
            assert release.wait(5)
            reply = super().complete(messages)
            reply.usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
            return reply

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Gated()) as service:
        try:
            view, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
            assert entered.wait(3)
            assert service.cancel(view.run.run_id).run.status == "cancel_requested"
        finally:
            release.set()
        final = service.wait(view.run.run_id)
        assert final.run.status == "cancelled" and len(final.spans) == 1
        assert final.spans[0].usage.total_tokens == 12 and not final.checkpoints


def test_document_process_crash_retains_initial_boundary_without_auto_resending(tmp_path):
    database = tmp_path / "runs.sqlite"
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, sys
from agenttinker.experiments import documents
from agenttinker.runtime.service import RunService, DocumentRunRequest
documents.search_documents = lambda *_: os._exit(0)
service = RunService(sys.argv[1])
view, _ = service.submit_document(DocumentRunRequest(mode='synthetic'), 'A')
service.wait(view.run.run_id)
""",
            str(database),
        ],
        check=True,
        timeout=15,
    )
    with SQLiteEventStore(database) as store:
        original = store.get_view(store.run_ids()[0])
        assert original.run.status == "running" and original.spans[-1].status == "running"
    with RunService(database, model_factory=lambda _: pytest.fail("automatic resend")) as service:
        after = service.get(original.run.run_id)
        assert after.run.status == "interrupted" and after.spans[-1].ended_at is None
        assert service.checkpoint_availability(after.run.run_id)[0].available


@pytest.mark.parametrize("indexed_calls", [False, True])
def test_document_http_sdk_auto_tools_versions_sse_and_no_key_history(
    tmp_path, monkeypatch, indexed_calls
):
    requests, clients = [], []
    driver = DocumentSyntheticModel()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        reply = driver.complete(body["messages"])
        if indexed_calls:
            for call in reply.message.get("tool_calls", []):
                call["index"] = 0
        return httpx.Response(
            200,
            json={
                "id": f"offline-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": reply.finish_reason,
                        "message": reply.message,
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    def offline_client(**kwargs):
        client = OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        clients.append(client)
        return client

    monkeypatch.setattr(sdk_module, "OpenAI", offline_client)
    database = tmp_path / "runs.sqlite"
    app = create_app(database)
    with TestClient(app) as client:
        scenarios = client.get("/api/v1/scenarios").json()
        assert [item["definition"]["ref"] for item in scenarios] == [
            corpus.EXPERIMENT_V2.model_dump(),
            corpus.EXPERIMENT.model_dump(),
        ]
        assert not requests
        body = {"mode": "live", "provider": "deepseek"}
        headers = {"Idempotency-Key": "A"}
        response = client.post(
            "/api/v1/scenarios/document-missing/runs", json=body, headers=headers
        )
        assert response.status_code == 201
        a = app.state.service.wait(response.json()["run"]["run_id"])
        assert a.run.status == "succeeded" and len(requests) == 4
        assert a.run.config.evaluator_versions == {"document-evidence": "1"}
        b_response = client.post(
            f"/api/v1/runs/{a.run.run_id}/forks",
            json=fork_request(a).model_dump(),
            headers={"Idempotency-Key": "B"},
        )
        assert b_response.status_code == 201
        b = app.state.service.wait(b_response.json()["run"]["run_id"])
        assert b.run.status == "succeeded" and len(requests) == 8
        models = [s for s in b.spans if s.kind == "model"]
        assert sum(s.usage.total_tokens for s in models) == 48
        assert all(s.input == s.output["request"] and s.cost.kind == "unknown" for s in models)
        assert all(body["tool_choice"] == "auto" for body in requests)
        assert all(
            len(body["tools"]) == 2 and "parallel_tool_calls" not in body for body in requests
        )
        assert all("strict" not in tool["function"] for body in requests for tool in body["tools"])
        assert all(body["thinking"] == {"type": "disabled"} for body in requests)
        assert all(
            "index" not in call
            for body in requests
            for message in body["messages"]
            for call in message.get("tool_calls", [])
        )
        if indexed_calls:
            first_model = next(span for span in a.spans if span.kind == "model")
            assert (
                first_model.output["raw_response"]["choices"][0]["message"]["tool_calls"][0][
                    "index"
                ]
                == 0
            )
            assert b.spans[0].input["tool_call"] == a.spans[1].input["tool_call"]
            assert b.spans[0].input["tool_call"]["index"] == 0
        monkeypatch.delenv("DEEPSEEK_API_KEY")
        assert (
            client.post(
                "/api/v1/scenarios/document-missing/runs",
                json=body,
                headers=headers,
            ).status_code
            == 200
        )
        missing = client.post(
            "/api/v1/scenarios/document-missing/runs",
            json={
                "mode": "live",
                "provider": "deepseek",
            },
            headers={"Idempotency-Key": "new-live"},
        )
        assert missing.status_code == 503 and missing.json()["detail"] == "provider_not_configured"
        for view in (a, b):
            route = f"/api/v1/runs/{view.run.run_id}"
            assert RunView.model_validate(client.get(route).json()) == view
            stream = client.get(route + "/events")
            assert project_events(sse_events(stream.iter_lines())) == view
            assert "offline-fixture-key" not in stream.text
        assert len(requests) == 8
        assert (
            client.post(
                "/api/v1/scenarios/unknown/runs",
                json={"mode": "synthetic"},
                headers={"Idempotency-Key": "missing"},
            ).status_code
            == 404
        )
    assert all(client.is_closed() for client in clients)
