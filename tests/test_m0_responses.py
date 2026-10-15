"""An unusable reply can still contain billable provider observations."""

import json
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from agenttinker.m0.accounting import PriceBook
from agenttinker.m0.cli import write_report
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.openai_model import OpenAIModel
from agenttinker.m0.probe import ProbeFailed, run_comparison

PRICE_PATH = Path(__file__).parents[1] / "examples/m0/pricing-deepseek-flash-peak.json"
USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 2,
    "total_tokens": 12,
    "prompt_cache_hit_tokens": 4,
    "prompt_cache_miss_tokens": 6,
}


@pytest.mark.parametrize("adapter", [OpenAIModel, DeepSeekModel])
@pytest.mark.parametrize("invalid_call", [1, 2], ids=["baseline", "branch"])
@pytest.mark.parametrize("choice_count", [0, 2], ids=["empty", "multiple"])
@pytest.mark.parametrize("usage", [USAGE, None], ids=["known_usage", "unknown_usage"])
def test_rejected_choices_preserve_response_and_new_usage(
    adapter, invalid_call, choice_count, usage, tmp_path
):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        call = len(requests)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "observed-search-1",
                    "type": "function",
                    "function": {"name": "search_documents", "arguments": '{"query":"release"}'},
                }
            ],
        }
        if call == 2:
            message = {"role": "assistant", "content": "Fictional summary [release-v2]."}
        return httpx.Response(
            200,
            json={
                "id": f"observed-response-{call}",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": index,
                        "message": message,
                        "finish_reason": "tool_calls" if call == 1 else "stop",
                    }
                    for index in range(choice_count if call == invalid_call else 1)
                ],
                "usage": usage,
                "provider_metadata": {"observation": "retained"},
            },
        )

    pricing = PriceBook.model_validate_json(PRICE_PATH.read_text()).model_copy(
        update={"provider": adapter.provider}
    )
    with OpenAI(
        api_key="offline-test-placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        with pytest.raises(ProbeFailed) as caught:
            run_comparison(adapter("deepseek-flash", client), pricing)

    # Check the serialized diagnostic, not just an exception's in-memory attributes.
    output = tmp_path / "rejected.failed.json"
    write_report(output, caught.value.report)
    report = json.loads(output.read_text())
    assert report["error"] == {"code": "ValueError", "stage": "model_protocol", "http_status": None}
    assert report["m0_real_call_verified"] is False
    assert len(requests) == invalid_call  # No retry or work after the rejected response.
    assert len(report["runs"]) == invalid_call
    run = report["runs"][-1]
    assert run["observed_status"] == "failed"
    assert run["new_model_calls"] == 1
    assert run["new_tool_attempts"] == (0 if invalid_call == 1 else 2)
    span = next(s for s in run["spans"] if s["kind"] == "model")
    assert span["status"] == "succeeded"  # The provider returned; the protocol was rejected.
    assert span["input"]["model"] == "deepseek-flash"
    assert span["output"]["response_id"] == f"observed-response-{invalid_call}"
    assert len(span["output"]["raw_response"]["choices"]) == choice_count
    assert span["output"]["raw_response"]["provider_metadata"] == {"observation": "retained"}
    if usage is not None:
        assert span["usage"]["total_tokens"] == 12
        assert run["new_usage"]["total_tokens"] == 12
        assert run["new_usage"]["coverage"] == {"recorded_calls": 1, "expected_calls": 1}
        assert run["new_cost"] == "0.000004224"
        assert run["new_cost_details"]["coverage"] == {"priced_calls": 1, "expected_calls": 1}
    else:
        assert span["usage"] is None
        assert run["new_usage"]["total_tokens"] is None
        assert run["new_cost"] is None
    if invalid_call == 2:
        assert run["parent_run_id"] == report["runs"][0]["run_id"]
        assert report["runs"][0]["execution_error"] is None
