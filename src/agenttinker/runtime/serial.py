"""A bounded model -> read-only tool -> model graph, with durable observations."""

import json
from copy import deepcopy
from importlib.metadata import version
from time import perf_counter
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agenttinker.core.records import CheckpointRef
from agenttinker.m0.fixtures import search_documents
from agenttinker.m0.openai_model import OpenAIModel
from agenttinker.m0.probe import SYSTEM
from agenttinker.m0.protocol import validate_reply
from agenttinker.runtime.journal import ExecutionFailed, RunJournal


class SerialState(TypedDict):
    messages: list[dict[str, Any]]
    tool_call: dict | None
    model_span_id: str | None
    tool_span_id: str | None
    documents: list[dict] | None


class SerialExecutor:
    def __init__(self, journal: RunJournal, request, model, tool=search_documents):
        self.journal, self.request, self.model, self.tool = journal, request, model, tool

    def model_node(self, state: SerialState):
        messages = deepcopy(state["messages"])
        request = (
            self.model._request(messages)
            if isinstance(self.model, OpenAIModel)
            else {"messages": deepcopy(messages)}
        )
        span = self.journal.begin(
            kind="model",
            logical_node_id="model",
            call_index=1 if state["documents"] is None else 2,
            input=request,
            provider=self.model.provider,
            parent_span_id=state["tool_span_id"],
        )
        start = perf_counter()
        try:
            reply = self.model.complete(messages)
        except Exception as error:
            self.journal.finish(
                span,
                duration_ms=(perf_counter() - start) * 1000,
                status="failed",
                output={"error_code": type(error).__name__},
            )
            raise ExecutionFailed(f"provider_error:{type(error).__name__}") from None
        self.journal.finish(
            span,
            duration_ms=(perf_counter() - start) * 1000,
            status="succeeded",
            output=reply.model_dump(),
            reply=reply,
        )
        try:
            call = validate_reply(reply, has_documents=state["documents"] is not None)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ExecutionFailed(f"model_protocol:{type(error).__name__}") from None
        return {
            "messages": [*state["messages"], reply.message],
            "tool_call": call,
            "model_span_id": span.span_id,
        }

    def tool_node(self, state: SerialState):
        call = state["tool_call"]
        args = json.loads(call["function"]["arguments"])
        for attempt in range(1, self.request.policy.tool_retry_limit + 2):
            span = self.journal.begin(
                kind="tool",
                logical_node_id="search_documents",
                call_index=1,
                parent_span_id=state["model_span_id"],
                logical_call_id=call["id"],
                attempt=attempt,
                input={
                    "tool_call": deepcopy(call),
                    "effective_policy": self.request.policy.model_dump(),
                },
            )
            start = perf_counter()
            error_code, origin, documents = None, "tool", None
            if self.request.inject_timeout and attempt == 1:
                error_code, origin = "TOOL_TIMEOUT", "injected"
            else:
                try:
                    documents = self.tool(args["query"], self.request.policy.top_k)
                except Exception as error:
                    error_code = type(error).__name__
            self.journal.finish(
                span,
                duration_ms=(perf_counter() - start) * 1000,
                status="failed" if error_code else "succeeded",
                output={"error_code": error_code, "origin": origin}
                if error_code
                else {"documents": documents},
            )
            if error_code:
                if self.journal.tool_failure(
                    span,
                    error_code=error_code,
                    origin=origin,
                    retry_limit=self.request.policy.tool_retry_limit,
                ):
                    continue
                raise ExecutionFailed(f"tool_error:{error_code}")
            return {
                "documents": documents,
                "tool_span_id": span.span_id,
                "messages": [
                    *state["messages"],
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(documents)},
                ],
            }
        raise ExecutionFailed("tool_retry_exhausted")

    def execute(self):
        graph = StateGraph(SerialState)
        graph.add_node("model", self.model_node)
        graph.add_node("tool", self.tool_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", lambda state: "tool" if state["tool_call"] else END)
        graph.add_edge("tool", "model")
        compiled = graph.compile(checkpointer=InMemorySaver(), interrupt_before=["tool"])
        config = {"configurable": {"thread_id": f"thread_{uuid4().hex}"}, "recursion_limit": 6}
        compiled.invoke(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": self.request.task},
                ],
                "tool_call": None,
                "model_span_id": None,
                "tool_span_id": None,
                "documents": None,
            },
            config,
        )
        snapshot = compiled.get_state(config)
        if snapshot.next != ("tool",):
            raise ExecutionFailed("tool_checkpoint_missing")
        self.journal.checkpoint(
            CheckpointRef(
                checkpoint_id=f"cp_{uuid4().hex}",
                run_id=self.journal.run_id,
                adapter="langgraph",
                runtime_version=version("langgraph"),
                agent_version="1",
                tool_versions={"search_documents": "1"},
                locator=snapshot.config["configurable"],
                # Saver lifetime is this execution; no persistent fork claim.
                allowed_patch_fields=(),
            )
        )
        compiled.invoke(None, snapshot.config)
