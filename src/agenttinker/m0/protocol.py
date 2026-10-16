"""The single-tool reply contract shared by the probe and M1 serial adapter."""

import json
from typing import Any

from agenttinker.m0.models import ModelOutput


def validate_reply(reply: ModelOutput, *, has_documents: bool) -> dict[str, Any] | None:
    if reply.choice_count is not None and reply.choice_count != 1:
        raise ValueError("M0 requires one model response choice")
    if reply.finish_reason not in {None, "stop", "tool_calls"}:
        raise ValueError("model_response_incomplete")
    message = reply.message
    calls = message.get("tool_calls") or []
    if calls:
        if has_documents or len(calls) != 1:
            raise ValueError("M0 requires exactly one tool call before the final answer")
        call = calls[0]
        if not isinstance(call.get("id"), str) or not call["id"].strip():
            raise ValueError("missing_tool_call_id")
        if call.get("type") != "function" or call["function"]["name"] != "search_documents":
            raise ValueError("M0 supports only search_documents")
        args = json.loads(call["function"]["arguments"])
        if (
            not isinstance(args, dict)
            or set(args) != {"query"}
            or not isinstance(args["query"], str)
            or not args["query"].strip()
        ):
            raise ValueError("search_documents requires a nonempty query string")
        return call
    if (
        not has_documents
        or not isinstance(message.get("content"), str)
        or not message["content"].strip()
    ):
        raise ValueError("Model did not call the required tool or return a final answer")
    return None
