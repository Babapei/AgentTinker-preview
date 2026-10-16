import sqlite3
import subprocess
import sys

import pytest

from agenttinker.runtime.checkpoints import (
    CheckpointUnavailable,
    checkpoint_path,
    open_checkpoints,
)
from agenttinker.runtime.serial import SerialExecutor
from agenttinker.runtime.service import RunRequest, RunService
from agenttinker.storage.sqlite import SQLiteEventStore


@pytest.mark.parametrize("inject_timeout", [False, True], ids=["succeeded", "failed"])
def test_old_tool_boundary_survives_process_exit_and_inspection_never_dispatches(
    tmp_path, inject_timeout
):
    database = tmp_path / "runs.sqlite"
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from agenttinker.runtime.service import RunRequest, RunService
with RunService(sys.argv[1]) as service:
    view, _ = service.submit(RunRequest(mode='synthetic', inject_timeout=sys.argv[2]=='True'), 'A')
    service.wait(view.run.run_id)
""",
            str(database),
            str(inject_timeout),
        ],
        check=True,
        timeout=15,
    )
    with SQLiteEventStore(database) as store:
        run_id = store.run_ids()[0]
        before = store.get_view(run_id)
        events = store.events(run_id)
    with RunService(
        database, model_factory=lambda _: pytest.fail("inspection dispatched")
    ) as service:
        reference = before.checkpoints[0]
        snapshot = service.resolve_checkpoint(run_id, reference.checkpoint_id)
        assert snapshot.next == ("tool",)
        assert snapshot.values["run_id"] == run_id
        assert snapshot.values["documents"] is None
        assert snapshot.values["messages"][-1] == before.spans[0].output["message"]
        assert snapshot.values["tool_call"]["id"] == "synthetic-search-1"
        assert (
            snapshot.config["configurable"]["checkpoint_id"] == reference.locator["checkpoint_id"]
        )
        with open_checkpoints(database) as saver:
            head = SerialExecutor.graph(saver).get_state(
                {"configurable": {"thread_id": reference.locator["thread_id"]}}
            )
            if not inject_timeout:
                assert head.config != snapshot.config
                assert head.values["documents"] is not None
        assert service.get(run_id) == before
    with SQLiteEventStore(database) as store:
        assert store.events(run_id) == events


def test_crash_in_tool_leaves_restorable_boundary_without_automatic_reexecution(tmp_path):
    database = tmp_path / "runs.sqlite"
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, sys
from agenttinker.runtime.service import RunRequest, RunService
service = RunService(sys.argv[1], tool=lambda *_: os._exit(0))
view, _ = service.submit(RunRequest(mode='synthetic', inject_timeout=False), 'A')
service.wait(view.run.run_id)
""",
            str(database),
        ],
        check=True,
        timeout=15,
    )
    with SQLiteEventStore(database) as store:
        before = store.get_view(store.run_ids()[0])
        assert before.run.status == "running"
        assert before.spans[-1].status == "running"
    with RunService(database, model_factory=lambda _: pytest.fail("restart dispatched")) as service:
        after = service.get(before.run.run_id)
        assert after.run.status == "interrupted"
        assert after.spans[-1].status == "interrupted"
        assert after.spans[-1].ended_at is None
        snapshot = service.resolve_checkpoint(after.run.run_id, after.checkpoints[0].checkpoint_id)
        assert snapshot.values["documents"] is None
        assert snapshot.next == ("tool",)
        assert after.last_seq == before.last_seq + 1


def test_resolution_rejects_missing_incompatible_and_foreign_states(tmp_path):
    database = tmp_path / "runs.sqlite"
    with RunService(database) as service:
        a, _ = service.submit(RunRequest(mode="synthetic"), "A")
        a = service.wait(a.run.run_id)
        b, _ = service.submit(RunRequest(mode="synthetic"), "B")
        b = service.wait(b.run.run_id)
        with pytest.raises(CheckpointUnavailable, match="checkpoint_missing"):
            service.resolve_checkpoint(a.run.run_id, "unknown")
        with open_checkpoints(database) as saver:
            incompatible = a.model_copy(
                update={
                    "run": a.run.model_copy(
                        update={
                            "config": a.run.config.model_copy(
                                update={"runtime_versions": {"langgraph": "incompatible"}}
                            )
                        }
                    )
                }
            )
            with pytest.raises(CheckpointUnavailable, match="runtime_incompatible"):
                SerialExecutor.load_checkpoint(saver, incompatible, a.checkpoints[0])
            foreign = a.checkpoints[0].model_copy(update={"locator": b.checkpoints[0].locator})
            with pytest.raises(CheckpointUnavailable, match="checkpoint_state_invalid"):
                SerialExecutor.load_checkpoint(
                    saver, a.model_copy(update={"checkpoints": (foreign,)}), foreign
                )
        with sqlite3.connect(checkpoint_path(database)) as connection:
            connection.execute("DELETE FROM checkpoints")
        with pytest.raises(CheckpointUnavailable, match="checkpoint_missing"):
            service.resolve_checkpoint(a.run.run_id, a.checkpoints[0].checkpoint_id)
        assert service.get(a.run.run_id) == a
