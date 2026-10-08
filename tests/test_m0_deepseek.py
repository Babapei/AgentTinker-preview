import json
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from agenttinker.m0.accounting import PriceBook
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.openai_model import SEARCH_TOOL, ProviderNotConfigured
from agenttinker.m0.probe import run_comparison


def test_deepseek_wire_parameters_and_cache_usage():
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        first = len(requests) == 1
        message = {"role": "assistant", "content": "Fictional release summary [release-v2]."}
        if first:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "ds-call-1",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": '{"query":"release"}',
                        },
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": f"ds-test-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if first else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt_cache_hit_tokens": 4,
                    "prompt_cache_miss_tokens": 6,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            },
        )

    with OpenAI(
        api_key="test-placeholder",
        base_url="https://api.deepseek.com",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        path = Path(__file__).parents[1] / "examples/m0/pricing-deepseek-flash-peak.json"
        pricing = PriceBook.model_validate_json(path.read_text())
        report = run_comparison(DeepSeekModel("deepseek-flash", client), pricing=pricing)
    assert len(requests) == 2
    for body in requests:
        assert body["thinking"] == {"type": "disabled"}
        assert body["max_tokens"] == 1024
        assert "max_completion_tokens" not in body
        assert "parallel_tool_calls" not in body
        assert "strict" not in body["tools"][0]["function"]
    assert requests[0]["tool_choice"]["function"]["name"] == "search_documents"
    assert requests[1]["tool_choice"] == "none"
    assert requests[1]["messages"][-1]["tool_call_id"] == "ds-call-1"
    assert report["provider"] == "deepseek"
    model_span = next(s for s in report["branch"]["spans"] if s["kind"] == "model")
    assert model_span["usage"]["prompt_cache_hit_tokens"] == 4
    assert model_span["usage"]["prompt_cache_miss_tokens"] == 6
    assert report["branch"]["new_usage"]["total_tokens"] == 12
    assert report["branch"]["new_cost"] == "0.000004224"
    assert report["branch"]["new_cost_details"]["coverage"]["expected_calls"] == 1
    assert SEARCH_TOOL["function"]["strict"] is True  # Other provider profile is unchanged.


def test_deepseek_never_uses_an_openai_key_as_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-placeholder")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    with pytest.raises(ProviderNotConfigured, match="DEEPSEEK_API_KEY"):
        DeepSeekModel.from_environment()
