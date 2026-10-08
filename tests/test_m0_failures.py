import json

import httpx
import pytest
from openai import OpenAI

from agenttinker.m0.cli import main, write_report
from agenttinker.m0.openai_model import OpenAIModel
from agenttinker.m0.probe import ProbeFailed, run_comparison
from agenttinker.m0.synthetic import SyntheticModel

TEST_USAGE = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}


class FailingFinalModel(SyntheticModel):
    def complete(self, messages):
        if messages[-1]["role"] == "tool":
            raise RuntimeError("private-error-marker-must-not-be-exported")
        return super().complete(messages).model_copy(update={"usage": TEST_USAGE})


def test_failed_branch_retains_baseline_known_usage_and_failed_call():
    with pytest.raises(ProbeFailed) as caught:
        run_comparison(FailingFinalModel())
    report = caught.value.report
    assert report["status"] == "failed"
    assert report["m0_real_call_verified"] is False
    assert report["error"]["stage"] == "model_call"
    a, b = report["runs"]
    assert a["state"]["status"] == "failed"  # Expected injected tool timeout, not an API failure.
    assert a["execution_error"] is None
    assert a["new_usage"]["total_tokens"] == 12
    assert b["parent_run_id"] == a["run_id"]
    assert b["new_tool_attempts"] == 2
    assert b["new_model_calls"] == 1
    assert b["observed_status"] == "failed"
    assert b["state"]["status"] == "running"  # Preserve what the last checkpoint actually stored.
    assert b["new_usage"]["total_tokens"] is None
    assert b["new_cost"] is None
    assert "private-error-marker" not in json.dumps(report)


def test_initial_provider_error_preserves_one_failed_call_and_http_status():
    def respond(request):
        return httpx.Response(429, json={"error": {"message": "private-error-marker"}})

    with OpenAI(
        api_key="test-placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        with pytest.raises(ProbeFailed) as caught:
            run_comparison(OpenAIModel("requested-model", client))
    report = caught.value.report
    assert report["error"] == {"code": "RateLimitError", "stage": "model_call", "http_status": 429}
    assert len(report["runs"]) == 1
    assert report["runs"][0]["new_model_calls"] == 1
    assert report["runs"][0]["new_tool_attempts"] == 0
    assert "private-error-marker" not in json.dumps(report)


@pytest.mark.parametrize("kind", ["length", "content_filter", "missing_id", "invalid_arguments"])
def test_incomplete_or_invalid_model_response_preserves_reply_and_never_executes_tool(kind):
    class InvalidModel(SyntheticModel):
        def complete(self, messages):
            reply = super().complete(messages)
            if kind in {"length", "content_filter"}:
                reply.finish_reason = kind
            elif kind == "missing_id":
                reply.message["tool_calls"][0]["id"] = ""
            else:
                reply.message["tool_calls"][0]["function"]["arguments"] = "not JSON"
            return reply

    with pytest.raises(ProbeFailed) as caught:
        run_comparison(InvalidModel())
    report = caught.value.report
    assert report["error"]["stage"] == "model_protocol"
    assert report["runs"][0]["new_tool_attempts"] == 0
    model_span = report["runs"][0]["spans"][0]
    assert (
        model_span["status"] == "succeeded"
    )  # A returned reply is distinct from protocol acceptance.
    assert model_span["output"]["message"]["tool_calls"]


def test_cli_writes_companion_diagnostic_and_preserves_previous_success(tmp_path, monkeypatch):
    output = tmp_path / "evidence.json"
    output.write_text("previous-success")
    monkeypatch.setattr(OpenAIModel, "from_environment", lambda model=None: FailingFinalModel())
    monkeypatch.setattr("sys.argv", ["agenttinker-m0", "--mode", "live", "--output", str(output)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert output.read_text() == "previous-success"
    diagnostic = json.loads((tmp_path / "evidence.failed.json").read_text())
    assert diagnostic["status"] == "failed"
    assert len(diagnostic["runs"]) == 2


def test_failed_serialization_does_not_truncate_existing_report(tmp_path):
    output = tmp_path / "evidence.json"
    output.write_text("previous-success")
    with pytest.raises(ValueError):
        write_report(output, {"invalid": float("nan")})
    assert output.read_text() == "previous-success"
    assert list(tmp_path.iterdir()) == [output]
