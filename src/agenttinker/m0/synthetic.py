"""A clearly labeled deterministic model substitute, with no fabricated usage."""

import json
from typing import Any, Literal

from agenttinker.m0.models import ModelOutput


class SyntheticModel:
    mode: Literal["synthetic"] = "synthetic"

    def complete(self, messages: list[dict[str, Any]]) -> ModelOutput:
        if messages[-1]["role"] == "tool":
            documents = json.loads(messages[-1]["content"])
            content = "Synthetic answer: " + "; ".join(doc["title"] for doc in documents)
            message = {"role": "assistant", "content": content}
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "synthetic-search-1",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps({"query": "release"}),
                        },
                    }
                ],
            }
        return ModelOutput(model="synthetic-deterministic-v1", message=message)
