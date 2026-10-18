"""Synthetic-only M5 bridge: existing executor nodes, Agent Server state ownership.

This is a research entry point, not a new production adapter. Agent Server owns
checkpoints/cancellation. Journal observations are custom stream events, never
AgentTinker database records or a substitute for its fork validation.
"""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from threading import RLock
from uuid import uuid4

from langgraph.config import get_stream_writer

from agenttinker.core.records import RunConfig
from agenttinker.experiments.document_model import DocumentBatchSyntheticModel
from agenttinker.m0.models import ToolPolicy
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.packages.portable import inspect_package, parse_package
from agenttinker.runtime.document_v2 import DocumentV2Executor
from agenttinker.runtime.journal import RunJournal
from agenttinker.runtime.serial import SerialExecutor
from agenttinker.runtime.service import RunRequest, runtime_versions

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {"timeout": "tool-timeout.json", "document": "document-missing-v2.json"}


def run_config(case, policy=None):
    """Keep case/agent/materials frozen while explicitly replacing the live driver."""
    _, records, _ = inspect_package(
        parse_package((ROOT / "examples/m4" / SOURCES[case]).read_bytes())
    )
    source = next(
        record.view.run.config for record in records.values() if not record.view.run.parent_run_id
    )
    data = source.model_dump(mode="json")
    data.update(
        provider="synthetic",
        requested_model=None,
        model_parameters={},
        runtime_versions=runtime_versions(),
    )
    if policy is not None:
        data["tool_policy"] = ToolPolicy.model_validate(policy).model_dump()
        if case == "document":
            data["variant"] = {"id": f"document-top{data['tool_policy']['top_k']}", "version": "1"}
    return RunConfig.model_validate(data)


def initial_state(case, run_id=None):
    config = run_config(case)
    executor = DocumentV2Executor if case == "document" else SerialExecutor
    # Both executors use the same initial model/tool state in their production path.
    from agenttinker.m0.probe import SYSTEM

    state = {
        "run_id": run_id or f"studio_{uuid4().hex}",
        "run_config": config.model_dump(mode="json"),
        "messages": [
            {"role": "system", "content": executor.SYSTEM if case == "document" else SYSTEM},
            {"role": "user", "content": config.task},
        ],
        "tool_call": None,
        "model_span_id": None,
        "tool_span_id": None,
    }
    return {
        **state,
        **(
            {
                "model_calls": 0,
                "tool_counts": {},
                "available_ids": [],
                "span_ids": [],
                "pending_calls": [],
            }
            if case == "document"
            else {"documents": None}
        ),
    }


class StreamJournal(RunJournal):
    """Reuse native Span/accounting emission; Agent Server owns run lifecycle."""

    def __init__(self, run_id):
        super().__init__(None, run_id, RLock(), None)

    def require_running(self):
        # This bridge has no RunService database; the server controls node scheduling.
        pass

    def emit(self, event_type, data, **metadata):
        get_stream_writer()(
            {
                "source": "m5_studio_node_observation",
                "type": event_type,
                "data": data.model_dump(mode="json") if hasattr(data, "model_dump") else data,
                **metadata,
            }
        )

    def tool_failure(self, span, *, error_code, origin, retry_limit):
        retry = span.attempt <= retry_limit
        self.emit(
            "tool.attempt_failed",
            {
                "error_code": error_code,
                "origin": origin,
                "retry_owner": "executor",
                "will_retry": retry,
            },
        )
        if retry:
            self.emit("tool.retry_scheduled", {"next_attempt": span.attempt + 1})
        return retry


class StudioMixin:
    def _intervention_input(self):
        # No platform Intervention was created by a generic Agent Server state edit.
        return {}


class StudioSerialExecutor(StudioMixin, SerialExecutor):
    pass


class StudioDocumentExecutor(StudioMixin, DocumentV2Executor):
    pass


class Nodes:
    def __init__(self, case):
        self.case = case

    def executor(self, state):
        config = RunConfig.model_validate(state["run_config"])
        if config != run_config(self.case, config.tool_policy):
            raise ValueError("studio_comparison_requires_frozen_synthetic_config")
        request = RunRequest(
            mode="synthetic",
            task=config.task,
            policy=ToolPolicy.model_validate(config.tool_policy),
            inject_timeout=config.fault_parameters["inject_timeout"],
        )
        cls, model = (
            (StudioDocumentExecutor, DocumentBatchSyntheticModel())
            if self.case == "document"
            else (StudioSerialExecutor, SyntheticModel())
        )
        return cls(StreamJournal(state["run_id"]), request, model)

    def model_node(self, state):
        return self.executor(state).model_node(deepcopy(state))

    def tool_node(self, state):
        return self.executor(state).tool_node(deepcopy(state))


def make_graph(case):
    cls = DocumentV2Executor if case == "document" else SerialExecutor
    # Keep native nodes/edges. The development server supplies persistence and
    # dynamic interrupts instead of RunService's private saver/boundary loop.
    return cls.graph(None, executor=Nodes(case)).builder.compile()


timeout = make_graph("timeout")
document = make_graph("document")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-directory", type=Path, required=True)
    directory = parser.parse_args().prepare_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    config = {
        "dependencies": [str(ROOT)],
        "graphs": {name: f"{Path(__file__).resolve()}:{name}" for name in SOURCES},
    }
    (directory / "langgraph.json").write_text(json.dumps(config, indent=2) + "\n")
    for name in SOURCES:
        (directory / f"input-{name}.json").write_text(
            json.dumps(initial_state(name), ensure_ascii=False, indent=2) + "\n"
        )
    print(json.dumps({"prepared": True, "directory": str(directory)}))
