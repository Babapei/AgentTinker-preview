"""A thin adapter over the official SDK's Chat Completions tool-call protocol."""

import os
from copy import deepcopy
from typing import Any, Literal
from urllib.parse import urlsplit

from openai import OpenAI

from agenttinker.m0.models import ModelOutput

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "Search fixed fictional release notes by query text.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class ProviderNotConfigured(ValueError):
    """No provider calls should occur until configuration is explicit."""


class OpenAIModel:
    mode: Literal["live"] = "live"

    def __init__(self, model: str, client: OpenAI):
        self.model = model
        self.client = client

    @classmethod
    def from_environment(cls, model: str | None = None) -> "OpenAIModel":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = (model or os.environ.get("OPENAI_MODEL", "")).strip()
        if not api_key or not model:
            raise ProviderNotConfigured(
                "provider_not_configured: set OPENAI_API_KEY and --model or OPENAI_MODEL"
            )
        base_url = os.environ.get("OPENAI_BASE_URL") or None
        if base_url:
            url = urlsplit(base_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ProviderNotConfigured(
                    "provider_not_configured: OPENAI_BASE_URL must be "
                    "an HTTP(S) URL without credentials"
                )
        # Disable invisible SDK retries; preserve inherited proxy and TLS settings.
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)
        return cls(model, client)

    def complete(self, messages: list[dict[str, Any]]) -> ModelOutput:
        answering = messages[-1]["role"] == "tool"
        request = {
            "model": self.model,
            "messages": deepcopy(messages),
            "tools": [deepcopy(SEARCH_TOOL)],
            "tool_choice": (
                "none"
                if answering
                else {"type": "function", "function": {"name": "search_documents"}}
            ),
            "parallel_tool_calls": False,
            "max_completion_tokens": 1024,
        }
        response = self.client.chat.completions.create(**request)
        if len(response.choices) != 1:
            raise ValueError("M0 requires one model response choice")
        choice = response.choices[0]
        message = {"role": "assistant", "content": choice.message.content}
        if choice.message.tool_calls:
            message["tool_calls"] = [
                c.model_dump(exclude_none=True) for c in choice.message.tool_calls
            ]
        return ModelOutput(
            model=response.model,
            message=message,
            usage=response.usage.model_dump() if response.usage is not None else None,
            request=request,
            response_id=response.id,
            finish_reason=choice.finish_reason,
            raw_response=response.model_dump(),
        )

    def close(self) -> None:
        self.client.close()
