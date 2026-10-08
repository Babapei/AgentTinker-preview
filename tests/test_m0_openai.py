import json
import os
import subprocess
import sys

import httpx
import pytest
from openai import OpenAI, RateLimitError

from agenttinker.m0.openai_model import OpenAIModel, ProviderNotConfigured
from agenttinker.m0.probe import CheckpointProbe, run_comparison


def test_official_sdk_preserves_tool_call_and_usage_without_replaying_prefix():
    requests = []
    original_arguments = '{ "query" : "release" }'

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        planning = body["messages"][-1]["role"] == "user"
        message = {"role": "assistant", "content": "Version 2 adds retries [release-v2]."}
        if planning:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "sdk-call-1",
                        "type": "function",
                        "function": {"name": "search_documents", "arguments": original_arguments},
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-test-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "returned-model-version",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if planning else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    with OpenAI(
        api_key="test-placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        report = run_comparison(OpenAIModel("requested-model", client))

    assert len(requests) == 2  # A's planning call and B's final-answer call only.
    assert requests[0]["tool_choice"]["function"]["name"] == "search_documents"
    assert requests[1]["tool_choice"] == "none"
    assert requests[0]["tools"][0]["function"]["strict"] is True
    assert (
        requests[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"] == original_arguments
    )
    assert requests[1]["messages"][-1]["tool_call_id"] == "sdk-call-1"
    assert report["checks"]["baseline_history_unchanged"] is True
    a_model = next(s for s in report["baseline"]["spans"] if s["kind"] == "model")
    b_model = next(s for s in report["branch"]["spans"] if s["kind"] == "model")
    assert a_model["input"]["model"] == "requested-model"
    assert b_model["output"]["model"] == "returned-model-version"
    assert b_model["usage"]["total_tokens"] == 12
    assert b_model["output"]["response_id"] == "chatcmpl-test-2"
    assert report["branch"]["new_cost"] is None


def test_sdk_error_records_failed_model_call_and_does_not_retry():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            429, json={"error": {"message": "test rate limit", "type": "rate_limit"}}
        )

    with OpenAI(
        api_key="test-placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        probe = CheckpointProbe(OpenAIModel("requested-model", client))
        with pytest.raises(RateLimitError):
            probe.run()
    assert len(requests) == 1
    spans = next(iter(probe.spans.values()))
    assert len(spans) == 1
    assert spans[0].status == "failed"
    assert spans[0].output == {"error_code": "RateLimitError"}
    assert spans[0].usage is None


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_live_configuration_must_be_explicit(monkeypatch, missing):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "requested-model")
    monkeypatch.delenv(missing)
    with pytest.raises(ProviderNotConfigured, match="provider_not_configured"):
        OpenAIModel.from_environment()


def test_live_cli_does_not_fallback_to_synthetic_or_write_success_report(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "OPENAI_MODEL"}}
    output = tmp_path / "live.json"
    result = subprocess.run(
        [sys.executable, "-m", "agenttinker.m0.cli", "--mode", "live", "--output", str(output)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "provider_not_configured" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "endpoint", ["file:///tmp/provider", "https://user:password@example.com/v1"]
)
def test_invalid_endpoint_is_rejected_before_client_creation(monkeypatch, endpoint):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "requested-model")
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    with pytest.raises(ProviderNotConfigured, match=r"HTTP\(S\)"):
        OpenAIModel.from_environment()
