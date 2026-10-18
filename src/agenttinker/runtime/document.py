"""Bounded serial ReAct: the model chooses tools; the executor controls policy."""

import json
from copy import deepcopy
from importlib.metadata import version
from time import perf_counter
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from agenttinker.core.records import CheckpointRef
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.document_model import validate_reply
from agenttinker.m0.openai_model import OpenAIModel
from agenttinker.runtime.checkpoints import (
    SAVER_ID,
    CheckpointUnavailable,
    checkpoint_config,
)
from agenttinker.runtime.journal import ExecutionFailed
from agenttinker.runtime.serial import SerialExecutor


class DocumentState(TypedDict):
    run_id: str
    run_config: dict
    messages: list[dict]
    tool_call: dict | None
    model_span_id: str | None
    tool_span_id: str | None
    model_calls: int
    tool_counts: dict[str, int]
    available_ids: list[str]
    span_ids: list[str]


class DocumentExecutor(SerialExecutor):
    # Reuse journal/config helpers; the legacy serial-checkpoint:2 graph stays intact.
    AGENT = corpus.AGENT
    PROMPT_VERSION = corpus.PROMPT_VERSION
    SYSTEM = corpus.SYSTEM

    def observe_model(self, state):
        self.journal.require_running()
        if state["model_calls"] >= corpus.MAX_MODEL_CALLS:
            raise ExecutionFailed("model_call_limit")
        messages = deepcopy(state["messages"])
        prepared = (
            self.model._request(messages)
            if isinstance(self.model, OpenAIModel)
            else {"messages": deepcopy(messages)}
        )
        span = self.journal.begin(
            kind="model",
            logical_node_id="model",
            call_index=state["model_calls"] + 1,
            parent_span_id=state["tool_span_id"],
            provider=self.model.provider,
            input=prepared,
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
        return messages, reply, span

    def model_node(self, state):
        messages, reply, span = self.observe_model(state)
        try:
            used = {call["id"] for message in messages for call in message.get("tool_calls", [])}
            call = validate_reply(reply, used)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ExecutionFailed(f"model_protocol:{type(error).__name__}") from None
        if call and state["model_calls"] + 1 == corpus.MAX_MODEL_CALLS:
            raise ExecutionFailed("model_call_limit")
        return {
            "messages": [*messages, reply.message],
            "tool_call": call,
            "model_span_id": span.span_id,
            "model_calls": state["model_calls"] + 1,
            "span_ids": [*state["span_ids"], span.span_id],
        }

    def tool_node(self, state):
        call = state["tool_call"]
        name, args = call["function"]["name"], json.loads(call["function"]["arguments"])
        index = state["tool_counts"].get(name, 0) + 1
        attempted = []
        for attempt in range(1, self.request.policy.tool_retry_limit + 2):
            span = self.journal.begin(
                kind="tool",
                logical_node_id=name,
                call_index=index,
                parent_span_id=state["model_span_id"],
                logical_call_id=call["id"],
                attempt=attempt,
                input={
                    "tool_call": deepcopy(call),
                    "effective_policy": self.request.policy.model_dump(),
                    **self._intervention_input(),
                },
            )
            attempted.append(span.span_id)
            start, error_code, output = perf_counter(), None, None
            try:
                output = (
                    {"documents": corpus.search_documents(args["query"], self.request.policy.top_k)}
                    if name == "search_documents"
                    else {
                        "document": corpus.read_document(
                            args["document_id"], tuple(state["available_ids"])
                        )
                    }
                )
            except Exception as error:
                error_code = (
                    error.code
                    if isinstance(error, corpus.DocumentAccessError)
                    else type(error).__name__
                )
            self.journal.finish(
                span,
                duration_ms=(perf_counter() - start) * 1000,
                status="failed" if error_code else "succeeded",
                output={"error_code": error_code, "origin": "tool"} if error_code else output,
            )
            if error_code:
                if self.journal.tool_failure(
                    span,
                    error_code=error_code,
                    origin="tool",
                    retry_limit=self.request.policy.tool_retry_limit,
                ):
                    continue
                raise ExecutionFailed(f"tool_error:{error_code}")
            available = list(state["available_ids"])
            for doc in output.get("documents", []):
                if doc["id"] not in available:
                    available.append(doc["id"])
            return {
                "available_ids": available,
                "tool_span_id": span.span_id,
                "tool_counts": {**state["tool_counts"], name: index},
                "span_ids": [*state["span_ids"], *attempted],
                "messages": [
                    *state["messages"],
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output)},
                ],
            }
        raise ExecutionFailed("tool_retry_exhausted")

    @classmethod
    def graph(cls, saver, *, executor=None):
        def read_only(_state):
            raise RuntimeError("checkpoint_inspection_cannot_execute")

        graph = StateGraph(DocumentState)
        graph.add_node("model", executor.model_node if executor else read_only)
        graph.add_node("tool", executor.tool_node if executor else read_only)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", lambda state: "tool" if state["tool_call"] else END)
        graph.add_edge("tool", "model")
        return graph.compile(checkpointer=saver, interrupt_before=["tool"])

    @classmethod
    def load_checkpoint(cls, saver, view, reference):
        config = checkpoint_config(
            view,
            reference,
            agent=cls.AGENT,
            prompt_version=cls.PROMPT_VERSION,
            tool_versions=corpus.TOOL_VERSIONS,
            expected_fixture_hash=corpus.fixture_hash(),
            recursion_limit=20,
        )
        if saver.get_tuple(config) is None:
            raise CheckpointUnavailable("checkpoint_missing")
        snapshot = cls.graph(saver).get_state(config)
        state = snapshot.values
        prefix = next((s for s in view.spans if s.span_id == state.get("model_span_id")), None)
        if (
            snapshot.next != ("tool",)
            or state.get("run_id") != view.run.run_id
            or state.get("run_config") != view.run.config.model_dump(mode="json")
            or not state.get("messages")
            or not isinstance(state.get("tool_call"), dict)
            or state["tool_call"].get("function", {}).get("name") != "search_documents"
            or state.get("tool_counts") != {}
            or state.get("available_ids") != []
            or state.get("tool_span_id") is not None
            or state.get("model_calls") != 1
            or state.get("span_ids") != [state.get("model_span_id")]
            or not (
                prefix is not None
                and prefix.kind == "model"
                and prefix.status == "succeeded"
                or state.get("model_span_id") in view.run.inherited_span_ids
            )
        ):
            raise CheckpointUnavailable("checkpoint_state_invalid")
        return snapshot

    def save_boundary(self, snapshot):
        state = snapshot.values
        forkable = (
            state["tool_call"]["function"]["name"] == "search_documents"
            and not state["tool_counts"]
        )
        self.journal.checkpoint(
            CheckpointRef(
                checkpoint_id=f"cp_{uuid4().hex}",
                run_id=self.journal.run_id,
                adapter="langgraph",
                runtime_version=version("langgraph"),
                agent_version=self.AGENT.version,
                tool_versions=corpus.TOOL_VERSIONS,
                locator={"store": SAVER_ID, **snapshot.config["configurable"]},
                allowed_patch_fields=("top_k",) if forkable else (),
            )
        )

    @staticmethod
    def _advance(compiled, value, config):
        # Follow the checkpoints emitted by THIS invocation, never a shared thread head.
        # Concurrent forks of the same historical point can append different branches.
        config = {**config, "recursion_limit": 20}
        latest = None
        for checkpoint in compiled.stream(value, config, stream_mode="checkpoints"):
            latest = checkpoint["config"]
        if latest is None:
            raise ExecutionFailed("tool_checkpoint_missing")
        return compiled.get_state(latest)

    def _continue(self, compiled, snapshot):
        # Every actual tool boundary is published; only the initial retrieval permits patching.
        while snapshot.next:
            if snapshot.next != ("tool",):
                raise ExecutionFailed("tool_checkpoint_missing")
            self.save_boundary(snapshot)
            snapshot = self._advance(compiled, None, snapshot.config)

    def execute(self, saver):
        compiled = self.graph(saver, executor=self)
        config = {"configurable": {"thread_id": f"thread_{uuid4().hex}"}, "recursion_limit": 20}
        snapshot = self._advance(
            compiled,
            {
                "run_id": self.journal.run_id,
                "run_config": self._run_config(),
                "messages": [
                    {"role": "system", "content": self.SYSTEM},
                    {"role": "user", "content": self.request.task},
                ],
                "tool_call": None,
                "model_span_id": None,
                "tool_span_id": None,
                "model_calls": 0,
                "tool_counts": {},
                "available_ids": [],
                "span_ids": [],
                **self.initial_extra_state(),
            },
            config,
        )
        self._continue(compiled, snapshot)

    def initial_extra_state(self):
        return {}

    def fork(self, saver, source, reference):
        snapshot = self.source_snapshot(saver, source, reference)
        compiled = self.graph(saver, executor=self)
        config = compiled.update_state(
            snapshot.config,
            {"run_id": self.journal.run_id, "run_config": self._run_config()},
            as_node="model",
        )
        config["recursion_limit"] = 20
        self._continue(compiled, compiled.get_state(config))

    def source_snapshot(self, saver, source, reference):
        return self.load_checkpoint(saver, source, reference)
