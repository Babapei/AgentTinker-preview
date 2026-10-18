"""Versioned serial tool queue with an individual checkpoint before each tool.

The graph follows LangGraph's model/tool loop. Keeping each tool as a graph step
gives the journal and checkpoint store a boundary inside a multi-intent response.
"""

from copy import deepcopy

from langgraph.graph import END, START, StateGraph

from agenttinker.experiments import documents as corpus
from agenttinker.experiments.document_model import validate_batch_reply
from agenttinker.m0.models import ModelOutput
from agenttinker.runtime.checkpoints import CheckpointUnavailable
from agenttinker.runtime.document import DocumentExecutor, DocumentState
from agenttinker.runtime.journal import ExecutionFailed
from agenttinker.storage.evaluations import AssessmentRejected, SQLiteEvaluationStore


class DocumentBatchState(DocumentState):
    pending_calls: list[dict]


class DocumentV2Executor(DocumentExecutor):
    AGENT = corpus.AGENT_V2
    PROMPT_VERSION = corpus.PROMPT_VERSION_V2
    SYSTEM = corpus.SYSTEM_V2

    def model_node(self, state):
        messages, reply, span = self.observe_model(state)
        calls = reply.message.get("tool_calls")
        remaining = corpus.MAX_TOOL_CALLS - sum(state["tool_counts"].values())
        if isinstance(calls, list) and len(calls) > remaining:
            raise ExecutionFailed("tool_call_limit")
        try:
            used = {call["id"] for message in messages for call in message.get("tool_calls", [])}
            pending = validate_batch_reply(reply, used)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ExecutionFailed(f"model_protocol:{type(error).__name__}") from None
        if pending and state["model_calls"] + 1 == corpus.MAX_MODEL_CALLS:
            raise ExecutionFailed("model_call_limit")
        return {
            "messages": [*messages, reply.message],
            "tool_call": pending[0] if pending else None,
            "pending_calls": pending,
            "model_span_id": span.span_id,
            "model_calls": state["model_calls"] + 1,
            "span_ids": [*state["span_ids"], span.span_id],
        }

    def tool_node(self, state):
        result = super().tool_node(state)
        pending = deepcopy(state["pending_calls"][1:])
        return {**result, "tool_call": pending[0] if pending else None, "pending_calls": pending}

    @classmethod
    def graph(cls, saver, *, executor=None):
        def read_only(_state):
            raise RuntimeError("checkpoint_inspection_cannot_execute")

        graph = StateGraph(DocumentBatchState)
        graph.add_node("model", executor.model_node if executor else read_only)
        graph.add_node("tool", executor.tool_node if executor else read_only)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", lambda state: "tool" if state["tool_call"] else END)
        graph.add_conditional_edges(
            "tool", lambda state: "tool" if state["pending_calls"] else "model"
        )
        return graph.compile(checkpointer=saver, interrupt_before=["tool"])

    def initial_extra_state(self):
        return {"pending_calls": []}

    @classmethod
    def load_checkpoint(cls, saver, view, reference, *, inherited=()):
        snapshot = super().load_checkpoint(saver, view, reference)
        state = snapshot.values
        # The forkable boundary is the entire unchanged first model response,
        # before any tool ran. Validate every queued intent and its exact order.
        try:
            messages = state["messages"]
            prefix = next(
                span for span in (*view.spans, *inherited) if span.span_id == state["model_span_id"]
            )
            reply = ModelOutput.model_validate(prefix.output)
            used = {
                call["id"] for message in messages[:-1] for call in message.get("tool_calls", [])
            }
            expected = validate_batch_reply(reply, used)
            valid = (
                bool(expected)
                and state.get("pending_calls") == expected
                and state["tool_call"] == expected[0]
                and len(messages) == 3
                and messages[0] == {"role": "system", "content": cls.SYSTEM}
                and messages[1] == {"role": "user", "content": view.run.config.task}
                and prefix.kind == "model"
                and prefix.status == "succeeded"
                and prefix.call_index == 1
                and reply.message == messages[-1]
                and prefix.input.get("messages") == messages[:-1]
            )
        except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
            valid = False
        if not valid:
            raise CheckpointUnavailable("checkpoint_state_invalid")
        return snapshot

    def source_snapshot(self, saver, source, reference):
        try:
            with SQLiteEvaluationStore(self.journal.database) as store:
                inherited = store.inherited_spans(source)
        except AssessmentRejected:
            raise CheckpointUnavailable("checkpoint_state_invalid") from None
        return self.load_checkpoint(saver, source, reference, inherited=inherited)
