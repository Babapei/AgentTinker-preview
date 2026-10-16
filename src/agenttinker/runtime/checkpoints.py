"""Local runtime state uses LangGraph's saver, separately from observation events."""

from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from agenttinker.m0.fixtures import fixture_hash

AGENT_ID = "serial-checkpoint"
AGENT_VERSION = "2"
TOOL_VERSIONS = {"search_documents": "1"}
SAVER_ID = "sqlite-v1"
PATCH_FIELDS = ("tool_retry_limit", "top_k")


def runtime_versions():
    return {
        name: version(name)
        for name in ("langgraph", "langgraph-checkpoint", "langgraph-checkpoint-sqlite", "openai")
    }


def checkpoint_path(database):
    return Path(str(database) + ".checkpoints.sqlite")


@contextmanager
def open_checkpoints(database):
    with SqliteSaver.from_conn_string(str(checkpoint_path(database))) as saver:
        yield saver


class ForkRejected(Exception):
    """Safe, stable reasons; never expose serialized state or filesystem errors."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class CheckpointUnavailable(ForkRejected):
    pass


def checkpoint_config(view, reference):
    run = view.run
    if reference not in view.checkpoints or reference.run_id != run.run_id:
        raise CheckpointUnavailable("checkpoint_missing")
    if (
        run.mode not in {"live", "synthetic"}
        or run.config.agent.id != AGENT_ID
        or run.config.agent.version != AGENT_VERSION
        or reference.adapter != "langgraph"
        or reference.agent_version != AGENT_VERSION
        or reference.runtime_version != version("langgraph")
        or reference.tool_versions != TOOL_VERSIONS
        or run.config.tool_versions != TOOL_VERSIONS
        or run.config.prompt_version != "single-tool-v1"
        or run.config.runtime_versions != runtime_versions()
        or run.config.fixture_hash != fixture_hash()
        or reference.locator.get("store") != SAVER_ID
    ):
        raise CheckpointUnavailable("runtime_incompatible")
    locator = reference.locator
    if (
        not isinstance(locator.get("thread_id"), str)
        or not locator["thread_id"]
        or not isinstance(locator.get("checkpoint_id"), str)
        or not locator["checkpoint_id"]
        or locator.get("checkpoint_ns") != ""
    ):
        raise CheckpointUnavailable("checkpoint_missing")
    # Always address the exact historical checkpoint, never the thread's latest head.
    return {
        "configurable": {
            key: locator[key] for key in ("thread_id", "checkpoint_ns", "checkpoint_id")
        },
        "recursion_limit": 6,
    }
