"""DeepSeek's non-thinking, standard-endpoint tool-call configuration."""

from typing import Any

from agenttinker.m0.openai_model import OpenAIModel


class DeepSeekModel(OpenAIModel):
    provider = "deepseek"
    env_prefix = "DEEPSEEK"
    default_base_url = "https://api.deepseek.com"

    def _request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        request = super()._request(messages)
        # strict requires the Beta endpoint; normal requests are locally validated in the graph.
        request["tools"][0]["function"].pop("strict")
        request.pop("parallel_tool_calls")
        request["max_tokens"] = request.pop("max_completion_tokens")
        # Named tool_choice is unsupported in DeepSeek's default thinking mode.
        request["extra_body"] = {"thinking": {"type": "disabled"}}
        return request
