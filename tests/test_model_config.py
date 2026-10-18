"""Offline SDK checks for frozen templates and legacy checkpoint compatibility."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from openai import OpenAI
from test_forks import saver_rows

import agenttinker.m0.openai_model as sdk_module
import agenttinker.runtime.service as service_module
from agenttinker.core.projection import RunView
from agenttinker.experiments.document_model import DocumentDeepSeekModel, DocumentSyntheticModel
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.runtime.checkpoints import ForkRejected
from agenttinker.runtime.model_config import (
    LEGACY_PARAMETER_KEYS,
    request_parameters,
    same_parameters,
)
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunRequest, RunService
from agenttinker.storage.sqlite import SQLiteEventStore


@pytest.fixture
def offline_sdk(monkeypatch):
    requests, clients = [], []
    for provider in ("DEEPSEEK", "OPENAI"):
        monkeypatch.setenv(f"{provider}_API_KEY", "offline-placeholder")
        monkeypatch.setenv(f"{provider}_MODEL", "offline-model")

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        driver = DocumentSyntheticModel() if len(body["tools"]) == 2 else SyntheticModel()
        reply = driver.complete(body["messages"])
        return httpx.Response(
            200,
            json={
                "id": f"offline-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-model",
                "choices": [
                    {"index": 0, "finish_reason": reply.finish_reason, "message": reply.message}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    def client_factory(**kwargs):
        client = OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        clients.append(client)
        client._test_generation = len(clients)
        return client

    monkeypatch.setattr(sdk_module, "OpenAI", client_factory)
    yield requests
    assert all(client.is_closed() for client in clients)


def submit(service, provider="deepseek", document=True):
    request_type = DocumentRunRequest if document else RunRequest
    create = service.submit_document if document else service.submit
    requested, _ = create(request_type(mode="live", provider=provider), "A")
    return service.wait(requested.run.run_id)


def fork_request(view, *, document=True):
    return ForkRequest(
        source_checkpoint_id=view.checkpoints[0].checkpoint_id,
        patch={"top_k": 3} if document else {"tool_retry_limit": 1},
    )


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
@pytest.mark.parametrize("document", [False, True])
def test_new_runs_freeze_tool_contract_and_fork_with_the_same_template(
    tmp_path, offline_sdk, provider, document
):
    database = tmp_path / "runs.sqlite"
    with RunService(database) as service:
        a = submit(service, provider, document)
        initial = next(span for span in a.spans if span.kind == "model")
        parameters = a.run.config.model_parameters
        assert same_parameters(parameters, request_parameters(initial.input))
        assert len(parameters["tools"]) == (2 if document else 1)
        assert parameters["tool_choice"] == (
            "auto" if document else {"type": "function", "function": {"name": "search_documents"}}
        )
        if provider == "openai":
            assert parameters["parallel_tool_calls"] is False
        else:
            assert "parallel_tool_calls" not in parameters
    with RunService(database) as service:
        b, _ = service.fork(a.run.run_id, fork_request(a, document=document), "B")
        b = service.wait(b.run.run_id)
        assert b.run.status == "succeeded"
        assert b.run.config.model_parameters == parameters
        assert service.get(a.run.run_id) == a
        assert offline_sdk


@pytest.mark.parametrize("document", [False, True])
def test_legacy_configuration_uses_observed_prefix_without_rewriting_old_facts(
    tmp_path, monkeypatch, offline_sdk, document
):
    database = tmp_path / "runs.sqlite"

    def legacy_parameters(prepared):
        return {
            key: deepcopy(value) for key, value in prepared.items() if key in LEGACY_PARAMETER_KEYS
        }

    # Reproduce the old configuration writer, without weakening the actual SDK
    # observations or modifying a persisted event/checkpoint after execution.
    with monkeypatch.context() as old:
        old.setattr(service_module, "request_parameters", legacy_parameters)
        with RunService(database) as service:
            a = submit(service, document=document)
    assert set(a.run.config.model_parameters) <= LEGACY_PARAMETER_KEYS
    before = saver_rows(database)
    with SQLiteEventStore(database) as store:
        events = store.events(a.run.run_id)
    with RunService(database) as service:
        b, _ = service.fork(a.run.run_id, fork_request(a, document=document), "B")
        b = service.wait(b.run.run_id)
        assert b.run.status == "succeeded"
        assert b.run.config.model_parameters == a.run.config.model_parameters
        # The first model is inherited from A, not a new first call in B.
        assert b.run.inherited_span_ids == (a.spans[0].span_id,)
        patch = {"top_k": 2} if document else {"top_k": 3}
        c, _ = service.fork(
            b.run.run_id,
            ForkRequest(source_checkpoint_id=b.checkpoints[0].checkpoint_id, patch=patch),
            "C",
        )
        assert service.wait(c.run.run_id).run.status == "succeeded"
        assert service.get(a.run.run_id) == a and service.get(b.run.run_id) == b
    after = saver_rows(database)
    old_ids = {row[2] for row in before["checkpoints"]}
    for table in before:
        assert [row for row in after[table] if row[2] in old_ids] == before[table]
    with SQLiteEventStore(database) as store:
        assert store.events(a.run.run_id) == events


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "drift", ["model", "tool_choice", "tools", "parallel_tool_calls", "temperature"]
)
def test_changed_template_rejects_fork_before_dispatch_without_consuming_key(
    tmp_path, monkeypatch, offline_sdk, legacy, drift
):
    database = tmp_path / "runs.sqlite"
    with monkeypatch.context() as old:
        if legacy:
            old.setattr(
                service_module,
                "request_parameters",
                lambda prepared: {
                    key: value for key, value in prepared.items() if key in LEGACY_PARAMETER_KEYS
                },
            )
        with RunService(database) as service:
            a = submit(service)
    request_count = len(offline_sdk)
    before = saver_rows(database)
    original = DocumentDeepSeekModel._request

    def changed(self, messages):
        prepared = original(self, messages)
        if drift == "tools":
            prepared["tools"][0]["function"]["description"] += " changed"
        else:
            prepared[drift] = {
                "model": "different-model",
                "tool_choice": "none",
                "parallel_tool_calls": False,
                "temperature": 0,
            }[drift]
        return prepared

    with RunService(database) as service:
        with monkeypatch.context() as altered:
            altered.setattr(DocumentDeepSeekModel, "_request", changed)
            with pytest.raises(ForkRejected, match="runtime_incompatible"):
                service.fork(a.run.run_id, fork_request(a), "B")
        assert len(offline_sdk) == request_count
        assert saver_rows(database) == before
        assert service.get(a.run.run_id) == a
        with SQLiteEventStore(database) as store:
            assert store.run_ids() == (a.run.run_id,)
        b, created = service.fork(a.run.run_id, fork_request(a), "B")
        assert created and service.wait(b.run.run_id).run.status == "succeeded"


def test_queued_execution_rechecks_template_before_any_sdk_request(
    tmp_path, monkeypatch, offline_sdk
):
    original = DocumentDeepSeekModel._request

    def changed_after_preflight(self, messages):
        prepared = original(self, messages)
        if self.client._test_generation > 1:
            prepared["tool_choice"] = "none"
        return prepared

    monkeypatch.setattr(DocumentDeepSeekModel, "_request", changed_after_preflight)
    with RunService(tmp_path / "runs.sqlite") as service:
        a = submit(service)
        assert a.run.status == "failed" and not a.spans and not a.checkpoints
        with SQLiteEventStore(service.database) as store:
            assert store.events(a.run.run_id)[-1].data.reason == "runtime_incompatible"
    assert offline_sdk == []


def test_parameter_comparison_preserves_json_types_and_snapshot_is_independent():
    prepared = {"model": "example", "messages": [], "tools": [{"name": "example"}], "flag": False}
    frozen = request_parameters(prepared)
    prepared["tools"][0]["name"] = "changed"
    assert frozen["tools"] == [{"name": "example"}]
    assert not same_parameters({"flag": False}, {"flag": 0})
    assert not same_parameters({"flag": True}, {"flag": 1})
    assert same_parameters({"a": 1, "b": 2}, {"b": 2, "a": 1})


@pytest.mark.parametrize(
    "reference,profile",
    [
        ("m3/deepseek-timeout-live.json", DeepSeekModel),
        ("m4/deepseek-document-live-observed.json", DocumentDeepSeekModel),
    ],
)
def test_saved_real_source_is_compatible_without_constructing_an_sdk_client(
    tmp_path, reference, profile
):
    path = Path(__file__).parents[1] / "examples" / reference
    before = path.read_bytes()
    source = RunView.model_validate(json.loads(before)["runs"]["A"])
    # The request builder is pure. An inert object cannot send a provider request.
    model = profile(source.run.config.requested_model, object())
    request = RunRequest(mode="live", provider="deepseek", model=source.run.config.requested_model)
    with RunService(tmp_path / "runs.sqlite") as service:
        service._check_model_config(model, request, source)
        with SQLiteEventStore(service.database) as store:
            assert store.run_ids() == ()
    assert path.read_bytes() == before
