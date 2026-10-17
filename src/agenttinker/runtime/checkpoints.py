"""Local runtime state uses LangGraph's saver, separately from observation events."""

from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from agenttinker.core.records import VersionRef
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


def checkpoint_config(
    view,
    reference,
    *,
    agent=None,
    prompt_version="single-tool-v1",
    tool_versions=None,
    expected_fixture_hash=None,
    recursion_limit=6,
):
    run = view.run
    agent = agent or VersionRef(id=AGENT_ID, version=AGENT_VERSION)
    tool_versions = TOOL_VERSIONS if tool_versions is None else tool_versions
    expected_fixture_hash = expected_fixture_hash or fixture_hash()
    if reference not in view.checkpoints or reference.run_id != run.run_id:
        raise CheckpointUnavailable("checkpoint_missing")
    if (
        run.mode not in {"live", "synthetic"}
        or run.config.agent != agent
        or reference.adapter != "langgraph"
        or reference.agent_version != agent.version
        or reference.runtime_version != version("langgraph")
        or reference.tool_versions != tool_versions
        or run.config.tool_versions != tool_versions
        or run.config.prompt_version != prompt_version
        or run.config.runtime_versions != runtime_versions()
        or run.config.fixture_hash != expected_fixture_hash
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
        "recursion_limit": recursion_limit,
    }
