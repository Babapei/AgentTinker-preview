"""Reuse official SDK observations, with an independently versioned auto-tool prompt."""

import json
from typing import Literal

from pydantic import Field

from agenttinker.core.records import Identifier, Text, ValueModel
from agenttinker.experiments import documents as corpus
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.models import ModelOutput
from agenttinker.m0.openai_model import OpenAIModel


class DocumentRequest:
    def _request(self, messages):
        request = super()._request(messages)
        for message in request["messages"]:
            for call in message.get("tool_calls", []):
                call.pop("index", None)  # Preserve observations; send only request-schema fields.
        request["tools"] = list(corpus.tool_schemas().values())
        request["tool_choice"] = "auto"
        if self.provider == "deepseek":
            for tool in request["tools"]:
                tool["function"].pop("strict")
        return request


class DocumentOpenAIModel(DocumentRequest, OpenAIModel):
    pass


class DocumentDeepSeekModel(DocumentRequest, DeepSeekModel):
    pass


class SearchArguments(ValueModel):
    query: Text = Field(max_length=2000)


class ReadArguments(ValueModel):
    document_id: Identifier


class FunctionCall(ValueModel):
    name: Literal["search_documents", "read_document"]
    arguments: str = Field(max_length=8000)


class ToolCall(ValueModel):
    id: Identifier
    type: Literal["function"]
    function: FunctionCall
    # Some Chat Completions providers retain a stream index on the final call.
    # It is observed metadata, never an execution argument or call identity.
    index: int | None = Field(default=None, strict=True, ge=0)


def validate_reply(reply: ModelOutput, used_call_ids: set[str]) -> dict | None:
    if reply.choice_count != 1 or reply.finish_reason not in {None, "stop", "tool_calls"}:
        raise ValueError("unusable_model_reply")
    if reply.message.get("role") != "assistant":
        raise ValueError("assistant_reply_required")
    calls = reply.message.get("tool_calls")
    if calls is not None and not isinstance(calls, list):
        raise ValueError("invalid_tool_calls")
    if calls:
        if not isinstance(calls, list) or len(calls) != 1:
            raise ValueError("one_serial_tool_call_required")
        call = ToolCall.model_validate(calls[0])
        if call.id in used_call_ids:
            raise ValueError("duplicate_tool_call_id")
        arguments = SearchArguments if call.function.name == "search_documents" else ReadArguments
        arguments.model_validate_json(call.function.arguments)
        return call.model_dump(exclude_none=True)
    if reply.finish_reason == "tool_calls":
        raise ValueError("missing_tool_call")
    content = reply.message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("final_answer_required")
    return None


class DocumentSyntheticModel:
    """Deterministic offline driver, never evidence of model autonomy or real usage."""

    mode, provider = "synthetic", "synthetic"

    def complete(self, messages):
        tool_messages = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        results = [doc for item in tool_messages for doc in item.get("documents", [])]
        read = {
            item["document"]["id"]: item["document"] for item in tool_messages if "document" in item
        }
        next_doc = next((doc for doc in results if doc["id"] not in read), None)
        if not tool_messages or next_doc:
            name = "read_document" if next_doc else "search_documents"
            arguments = {"document_id": next_doc["id"]} if next_doc else {"query": "release"}
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"document-tool-{len(tool_messages) + 1}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            }
        else:
            answer = "synthetic answer: " + " ".join(
                f"{doc['text']} [{doc['id']}]" for doc in read.values()
            )
            if not set(corpus.dataset_case().required_document_ids) <= read.keys():
                answer += " 材料不足，无法确认引用修复。"
            message = {"role": "assistant", "content": answer}
        return ModelOutput(
            provider=self.provider,
            model="document-synthetic-v1",
            message=message,
            usage=None,
            request={"messages": messages},
            choice_count=1,
            finish_reason="tool_calls" if message.get("tool_calls") else "stop",
        )


def document_model(request):
    if request.mode == "synthetic":
        return DocumentSyntheticModel()
    profile = DocumentDeepSeekModel if request.provider == "deepseek" else DocumentOpenAIModel
    return profile.from_environment(request.model)
