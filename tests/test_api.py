import asyncio
import json
import socket
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from openai import OpenAI

import agenttinker.api.app as api_module
import agenttinker.m0.openai_model as sdk_module
from agenttinker.api.app import create_app
from agenttinker.core.events import parse_event
from agenttinker.core.projection import RunView, project_events
from agenttinker.core.schema import protocol_schemas
from agenttinker.m0.accounting import PriceBook
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.runtime.service import RunService


def sse_events(lines):
    events, fields = [], {}
    for line in lines:
        if not line:
            if fields:
                event = parse_event(json.loads(fields["data"]))
                assert fields["id"] == f"{event.run_id}:{event.seq}"
                assert fields["event"] == event.type
                events.append(event)
                fields = {}
        elif not line.startswith(":"):
            key, _, value = line.partition(": ")
            fields[key] = value
    assert not fields
    return events


@pytest.mark.parametrize("retry_limit,status", [(0, "failed"), (1, "succeeded")])
def test_http_execution_reads_and_sse_rebuild_the_same_history(tmp_path, retry_limit, status):
    app = create_app(tmp_path / "runs.sqlite")
    with TestClient(app) as client:
        body = {"mode": "synthetic", "policy": {"tool_retry_limit": retry_limit}}
        response = client.post("/api/v1/runs", json=body, headers={"Idempotency-Key": "first"})
        assert response.status_code == 201
        run_id = response.json()["run"]["run_id"]
        final = app.state.service.wait(run_id)
        assert final.run.status == status
        route = f"/api/v1/runs/{run_id}"
        assert response.headers["location"] == route
        assert RunView.model_validate(client.get(route).json()) == final
        again = client.post("/api/v1/runs", json=body, headers={"Idempotency-Key": "first"})
        assert again.status_code == 200
        assert RunView.model_validate(again.json()) == final
        conflict = client.post(
            "/api/v1/runs",
            json={**body, "inject_timeout": False},
            headers={"Idempotency-Key": "first"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "idempotency_key_payload_conflict"
        assert client.get("/api/v1/runs").json()["total"] == 1
        spans = client.get(route + "/spans", params={"limit": 1}).json()
        assert len(spans["items"]) == 1 and spans["next_offset"] == 1
        failed = client.get(route + "/spans", params={"failed_only": True}).json()
        assert failed["total"] == 1
        node = failed["items"][0]["logical_node_id"]
        tools = client.get(route + "/spans", params={"logical_node_id": node}).json()
        assert tools["total"] == retry_limit + 1
        assert len(client.get(route + "/checkpoints").json()) == 1
        assert client.post(route + "/cancel").status_code == 200
        assert client.get(route).json()["run"]["status"] == status
        stream = client.get(route + "/events")
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["x-accel-buffering"] == "no"
        events = sse_events(stream.iter_lines())
        assert [e.seq for e in events] == list(range(1, final.last_seq + 1))
        assert len({e.event_id for e in events}) == len(events)
        assert project_events(events) == final
        assert all(s.usage.total_tokens is None for s in final.spans)


def test_history_and_idempotency_survive_server_restart_without_execution(tmp_path):
    path = tmp_path / "runs.sqlite"
    body, headers = {"mode": "synthetic", "inject_timeout": False}, {"Idempotency-Key": "saved"}
    app = create_app(path)
    with TestClient(app) as client:
        run_id = client.post("/api/v1/runs", json=body, headers=headers).json()["run"]["run_id"]
        final = app.state.service.wait(run_id)

    def forbid_call(_request):
        raise AssertionError("history_must_not_execute")

    restarted = create_app(
        path, service_factory=lambda db, **kw: RunService(db, model_factory=forbid_call, **kw)
    )
    with TestClient(restarted) as client:
        route = f"/api/v1/runs/{run_id}"
        assert RunView.model_validate(client.get(route).json()) == final
        assert client.get("/api/v1/runs").json()["items"][0]["run_id"] == run_id
        replay = client.post("/api/v1/runs", json=body, headers=headers)
        assert replay.status_code == 200
        assert RunView.model_validate(replay.json()) == final
        for cursor in (0, 2, final.last_seq):
            via_header = client.get(
                route + "/events", headers={"Last-Event-ID": f"{run_id}:{cursor}"}
            )
            via_query = client.get(route + "/events", params={"after_seq": cursor})
            assert via_header.text == via_query.text
            events = sse_events(via_header.iter_lines())
            assert [e.seq for e in events] == list(range(cursor + 1, final.last_seq + 1))


@pytest.mark.parametrize("reject_choices", [False, True], ids=["tool_then_answer", "bad_choices"])
def test_default_sdk_path_keeps_wire_observations_and_cost_in_http_history(
    tmp_path, monkeypatch, reject_choices
):
    # The production factory and SDK execute against an offline HTTP transport only.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sdk-fixture-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://provider.invalid")
    requests, clients = [], []
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "prompt_cache_hit_tokens": 4,
        "prompt_cache_miss_tokens": 6,
    }

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        message = SyntheticModel().complete(body["messages"]).message
        return httpx.Response(
            200,
            json={
                "id": f"offline-response-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": []
                if reject_choices
                else [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                        "message": message,
                    }
                ],
                "usage": usage,
            },
        )

    def offline_client(**kwargs):
        client = OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        clients.append(client)
        return client

    monkeypatch.setattr(sdk_module, "OpenAI", offline_client)
    price = PriceBook.model_validate_json(
        (Path(__file__).parents[1] / "examples/m0/pricing-deepseek-flash-peak.json").read_text()
    )
    app = create_app(tmp_path / "runs.sqlite", pricing=price)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            json={"mode": "live", "provider": "deepseek", "inject_timeout": False},
            headers={"Idempotency-Key": "sdk-offline"},
        )
        assert response.status_code == 201
        run_id = response.json()["run"]["run_id"]
        final = app.state.service.wait(run_id)
        assert final.run.status == ("failed" if reject_choices else "succeeded")
        assert len(requests) == (1 if reject_choices else 2)
        assert final.run.config.requested_model == "deepseek-flash"
        assert final.run.config.model_parameters == {
            "max_tokens": 1024,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        assert all(body["thinking"] == {"type": "disabled"} for body in requests)
        models = [s for s in final.spans if s.kind == "model"]
        for span in models:
            assert span.input == span.output["request"]
            assert span.output["response_id"].startswith("offline-response-")
            assert span.output["raw_response"]["usage"]["total_tokens"] == 12
            assert span.usage.total_tokens == 12 and span.usage.cached_input_tokens == 4
            assert span.cost.kind == "estimate" and span.cost.price_version == price.version
            assert str(span.cost.amount) == "0.000004224"
        streamed = client.get(f"/api/v1/runs/{run_id}/events")
        assert project_events(sse_events(streamed.iter_lines())) == final
        assert "sdk-fixture-key" not in streamed.text
        assert "sdk-fixture-key" not in final.model_dump_json()
    assert len(clients) == 2 and all(client.is_closed() for client in clients)


@pytest.mark.parametrize(
    "query,header,code",
    [
        ({"after_seq": -1}, None, None),
        ({"after_seq": "true"}, None, None),
        ({"after_seq": 99999}, None, "event_cursor_ahead"),
        ({}, "run_other:1", "invalid_event_cursor"),
        ({}, "malformed", "invalid_event_cursor"),
        ({}, "{run_id}:-1", "invalid_event_cursor"),
        ({"after_seq": 1}, "{run_id}:2", "conflicting_event_cursors"),
    ],
)
def test_invalid_cursors_fail_before_stream_headers(tmp_path, query, header, code):
    app = create_app(tmp_path / "runs.sqlite")
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/runs", json={"mode": "synthetic"}, headers={"Idempotency-Key": "cursor"}
        )
        run_id = created.json()["run"]["run_id"]
        app.state.service.wait(run_id)
        headers = {"Last-Event-ID": header.format(run_id=run_id)} if header else {}
        response = client.get(f"/api/v1/runs/{run_id}/events", params=query, headers=headers)
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/json"
        if code:
            assert response.json()["detail"] == code


def test_explicit_mode_configuration_and_missing_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "offline-model-id")
    with TestClient(create_app(tmp_path / "runs.sqlite")) as client:
        for body in ({}, {"mode": "synthetic", "provider": "deepseek"}, {"mode": "live"}):
            assert (
                client.post(
                    "/api/v1/runs", json=body, headers={"Idempotency-Key": "invalid"}
                ).status_code
                == 422
            )
        assert client.post("/api/v1/runs", json={"mode": "synthetic"}).status_code == 422
        missing = client.post(
            "/api/v1/runs",
            json={"mode": "live", "provider": "deepseek"},
            headers={"Idempotency-Key": "unconfigured"},
        )
        assert missing.status_code == 503
        assert missing.json() == {"detail": "provider_not_configured"}
        assert client.get("/api/v1/runs").json()["items"] == []
        for suffix in ("", "/spans", "/checkpoints", "/events"):
            assert client.get("/api/v1/runs/run_missing" + suffix).status_code == 404
        assert client.post("/api/v1/runs/run_missing/cancel").status_code == 404
        assert client.get("/api/v1/protocol").json() == protocol_schemas()
        schema = client.get("/openapi.json").json()
        assert {"RunRequest", "RunView", "SpanPage"} <= schema["components"]["schemas"].keys()


def test_sse_keeps_terminal_event_committed_after_an_empty_read(tmp_path, monkeypatch):
    entered, release = Event(), Event()

    class Gated(SyntheticModel):
        def complete(self, messages):
            entered.set()
            assert release.wait(5)
            return super().complete(messages)

    app = create_app(
        tmp_path / "runs.sqlite",
        service_factory=lambda db, **kw: RunService(db, model_factory=lambda _: Gated(), **kw),
    )
    original_read = api_module.read_events
    raced = False
    with TestClient(app) as client:
        try:
            created = client.post(
                "/api/v1/runs", json={"mode": "synthetic"}, headers={"Idempotency-Key": "race"}
            )
            run_id = created.json()["run"]["run_id"]
            assert entered.wait(3)
            cursor = app.state.service.get(run_id).last_seq

            def race_read(database, key, after):
                nonlocal raced
                events = original_read(database, key, after)
                if not raced:
                    assert not events
                    raced = True
                    release.set()
                    app.state.service.wait(run_id)
                return events

            monkeypatch.setattr(api_module, "read_events", race_read)
            response = client.get(f"/api/v1/runs/{run_id}/events?after_seq={cursor}")
            events = sse_events(response.iter_lines())
            assert raced and events[-1].data.after == "failed"
            final = app.state.service.get(run_id)
            assert [e.seq for e in events] == list(range(cursor + 1, final.last_seq + 1))
        finally:
            release.set()


@contextmanager
def local_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=2, ws="none")
    )
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 5
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()


def test_real_http_disconnect_reconnect_and_cancel_preserve_inflight_result(tmp_path):
    entered, release = Event(), Event()
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}

    class Gated(SyntheticModel):
        calls = 0

        def complete(self, messages):
            self.calls += 1
            entered.set()
            assert release.wait(8)
            return super().complete(messages).model_copy(update={"usage": usage})

    model = Gated()
    app = create_app(
        tmp_path / "runs.sqlite",
        service_factory=lambda db, **kw: RunService(db, model_factory=lambda _: model, **kw),
        poll_interval=0.01,
        heartbeat_interval=0.03,
    )
    try:
        with (
            local_server(app) as base_url,
            httpx.Client(base_url=base_url, trust_env=False) as client,
        ):
            try:
                created = client.post(
                    "/api/v1/runs",
                    json={"mode": "synthetic", "inject_timeout": False},
                    headers={"Idempotency-Key": "network"},
                )
                assert created.status_code == 201
                run_id = created.json()["run"]["run_id"]
                route = f"/api/v1/runs/{run_id}"
                assert entered.wait(3)
                initial_lines = []
                with client.stream("GET", route + "/events") as response:
                    assert response.status_code == 200
                    for line in response.iter_lines():
                        if line == ": keep-alive":
                            break
                        initial_lines.append(line)
                initial = sse_events(initial_lines)
                assert initial[-1].type == "span.started"
                assert client.get(route).json()["run"]["status"] == "running"
                cursor = initial[-1].seq
                cancel = client.post(route + "/cancel")
                assert cancel.status_code == 202
                assert cancel.json()["run"]["status"] == "cancel_requested"
                assert cancel.json()["spans"][0]["usage"]["total_tokens"] is None
                assert client.post(route + "/cancel").json() == cancel.json()
            finally:
                release.set()
            final = app.state.service.wait(run_id)
            response = client.get(
                route + "/events", headers={"Last-Event-ID": f"{run_id}:{cursor}"}
            )
            resumed = sse_events(response.iter_lines())
            all_events = initial + resumed
            assert [e.seq for e in all_events] == list(range(1, final.last_seq + 1))
            assert len({e.event_id for e in all_events}) == len(all_events)
            assert project_events(all_events) == final
            assert final.run.status == "cancelled" and model.calls == 1
            assert final.spans[0].usage.total_tokens == 12
            assert final.spans[0].usage.raw == usage
            assert client.post(route + "/cancel").status_code == 200
    finally:
        release.set()
    assert not app.state.service._owner.is_locked


def test_stream_disconnect_exits_without_reading_or_cancelling(tmp_path):
    class Disconnected:
        async def is_disconnected(self):
            return True

    async def consume():
        return [
            item
            async for item in api_module.stream_events(
                tmp_path / "not-created.sqlite",
                "run_missing",
                0,
                Disconnected(),
                poll_interval=0.01,
                heartbeat_interval=1,
            )
        ]

    assert asyncio.run(consume()) == []
    assert not (tmp_path / "not-created.sqlite").exists()
