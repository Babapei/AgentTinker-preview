"""A bounded model -> read-only tool -> model graph, with durable observations."""

import json
from copy import deepcopy
from importlib.metadata import version
from time import perf_counter
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from agenttinker.core.records import CheckpointRef
from agenttinker.m0.fixtures import search_documents
from agenttinker.m0.openai_model import OpenAIModel
from agenttinker.m0.probe import SYSTEM
from agenttinker.m0.protocol import validate_reply
from agenttinker.runtime.checkpoints import (
    AGENT_VERSION,
    PATCH_FIELDS,
    SAVER_ID,
    TOOL_VERSIONS,
    CheckpointUnavailable,
    checkpoint_config,
)
from agenttinker.runtime.journal import ExecutionFailed, RunJournal
from agenttinker.storage.sqlite import SQLiteEventStore


class SerialState(TypedDict):
    run_id: str
    run_config: dict
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
                    **self._intervention_input(),
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

    @classmethod
    def graph(cls, saver, *, executor=None):
        def read_only(_state):
            raise RuntimeError("checkpoint_inspection_cannot_execute")

        graph = StateGraph(SerialState)
        graph.add_node("model", executor.model_node if executor else read_only)
        graph.add_node("tool", executor.tool_node if executor else read_only)
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model", lambda state: "tool" if state["tool_call"] else END, {"tool": "tool", END: END}
        )
        graph.add_edge("tool", "model")
        return graph.compile(checkpointer=saver, interrupt_before=["tool"])

    @classmethod
    def load_checkpoint(cls, saver, view, reference):
        config = checkpoint_config(view, reference)
        if saver.get_tuple(config) is None:
            raise CheckpointUnavailable("checkpoint_missing")
        snapshot = cls.graph(saver).get_state(config)
        state = snapshot.values
        prefix = next(
            (span for span in view.spans if span.span_id == state.get("model_span_id")), None
        )
        if (
            snapshot.next != ("tool",)
            or state.get("run_id") != view.run.run_id
            or state.get("run_config") != view.run.config.model_dump(mode="json")
            or state.get("documents") is not None
            or state.get("tool_span_id") is not None
            or not state.get("tool_call")
            or not state.get("messages")
            or not (
                prefix is not None
                and prefix.kind == "model"
                and prefix.status == "succeeded"
                or state.get("model_span_id") in view.run.inherited_span_ids
            )
        ):
            raise CheckpointUnavailable("checkpoint_state_invalid")
        return snapshot

    def execute(self, saver):
        compiled = self.graph(saver, executor=self)
        config = {"configurable": {"thread_id": f"thread_{uuid4().hex}"}, "recursion_limit": 6}
        compiled.invoke(
            {
                "run_id": self.journal.run_id,
                "run_config": self._run_config(),
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
        self.save_boundary(snapshot)
        compiled.invoke(None, snapshot.config)

    def save_boundary(self, snapshot):
        self.journal.checkpoint(
            CheckpointRef(
                checkpoint_id=f"cp_{uuid4().hex}",
                run_id=self.journal.run_id,
                adapter="langgraph",
                runtime_version=version("langgraph"),
                agent_version=AGENT_VERSION,
                tool_versions=TOOL_VERSIONS,
                locator={"store": SAVER_ID, **snapshot.config["configurable"]},
                allowed_patch_fields=PATCH_FIELDS,
            )
        )

    def fork(self, saver, source, reference):
        snapshot = self.load_checkpoint(saver, source, reference)
        compiled = self.graph(saver, executor=self)
        config = compiled.update_state(
            snapshot.config,
            {"run_id": self.journal.run_id, "run_config": self._run_config()},
            as_node="model",
        )
        config["recursion_limit"] = 6
        boundary = compiled.get_state(config)
        if boundary.next != ("tool",):
            raise ExecutionFailed("tool_checkpoint_missing")
        self.save_boundary(boundary)
        compiled.invoke(None, config)

    def _intervention_input(self):
        with SQLiteEventStore(self.journal.database) as store:
            intervention = store.get_view(self.journal.run_id).run.intervention
            return {"intervention_id": intervention.intervention_id} if intervention else {}

    def _run_config(self):
        with SQLiteEventStore(self.journal.database) as store:
            return store.get_view(self.journal.run_id).run.config.model_dump(mode="json")
