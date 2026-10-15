import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from agenttinker.core.records import CheckpointRef, Cost, Run, Span, Usage
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore


def test_restart_reads_complete_history_and_cursor(run_record, make_event, tmp_path):
    path = tmp_path / "runs.sqlite"
    log = [
        make_event(1, "run.created", run_record),
        make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
        make_event(3, "run.status_changed", {"before": "running", "after": "failed"}),
    ]
    with SQLiteEventStore(path) as store:
        for event in log:
            store.append(event)
        expected = store.get_view("run_A")
    with SQLiteEventStore(path) as reopened:
        assert reopened.get_view("run_A") == expected
        assert reopened.get_view("run_A").run.status == "failed"
        assert reopened.events("run_A") == tuple(log)
        assert reopened.events("run_A", after_seq=1, limit=1) == (log[1],)
        assert reopened.events("run_A", after_seq=3) == ()
        assert reopened.run_ids() == ("run_A",)
        with pytest.raises(ValueError, match="cursor_ahead"):
            reopened.events("run_A", after_seq=4)
        with pytest.raises(ValueError):
            reopened.events("run_A", after_seq=True)
        with pytest.raises(KeyError):
            reopened.events("missing")


def test_identical_retry_is_idempotent_but_conflicts_preserve_old_facts(
    run_record, make_event, tmp_path
):
    first = make_event(1, "run.created", run_record)
    second = make_event(2, "run.status_changed", {"before": "queued", "after": "running"})
    with SQLiteEventStore(tmp_path / "runs.sqlite") as store:
        assert store.append(first) == store.append(first)
        with pytest.raises(EventConflict, match="event_id_conflict"):
            store.append(second.model_copy(update={"event_id": first.event_id}))
        store.append(second)
        with pytest.raises(EventConflict, match="sequence_conflict"):
            store.append(second.model_copy(update={"event_id": "different"}))
        with pytest.raises(EventConflict, match="sequence_conflict"):
            store.append(second.model_copy(update={"event_id": "gap", "seq": 4}))
        with pytest.raises(ValueError, match="stale_run_status"):
            store.append(
                make_event(3, "run.status_changed", {"before": "queued", "after": "failed"})
            )
        assert store.events("run_A") == (first, second)
        assert store.get_view("run_A").last_seq == 2


def test_database_failure_rolls_back_projection_and_event_together(
    run_record, make_event, tmp_path
):
    path = tmp_path / "runs.sqlite"
    with SQLiteEventStore(path) as store:
        store.append(make_event(1, "run.created", run_record))
        before = store.get_view("run_A")
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TRIGGER fail_event BEFORE INSERT ON events "
                "WHEN NEW.seq=2 BEGIN SELECT RAISE(ABORT, 'injected write failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            store.append(
                make_event(2, "run.status_changed", {"before": "queued", "after": "running"})
            )
        assert store.get_view("run_A") == before
        assert len(store.events("run_A")) == 1
    with SQLiteEventStore(path) as reopened:
        assert reopened.get_view("run_A") == before


def test_cached_view_can_be_rebuilt_without_changing_events(run_record, make_event, tmp_path):
    path = tmp_path / "runs.sqlite"
    with SQLiteEventStore(path) as store:
        store.append(make_event(1, "run.created", run_record))
        original = store.events("run_A")
        view = store.get_view("run_A")
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE runs SET view_json='{}' WHERE run_id='run_A'")
        with pytest.raises(ValidationError):
            store.get_view("run_A")
        assert store.rebuild_view("run_A") == view
        assert store.events("run_A") == original
        returned = store.get_view("run_A")
        returned.run.config.model_parameters["mutated"] = True
        assert "mutated" not in store.get_view("run_A").run.config.model_parameters


def test_transaction_allocates_sequences_across_independent_writers(
    run_record, make_event, tmp_path
):
    path = tmp_path / "runs.sqlite"
    with SQLiteEventStore(path) as store:
        store.append(make_event(1, "run.created", run_record))
        store.append(make_event(2, "run.status_changed", {"before": "queued", "after": "running"}))

    def write(index):
        draft = {
            "event_id": f"checkpoint_event_{index}",
            "run_id": "run_A",
            "occurred_at": run_record.created_at,
            "type": "checkpoint.saved",
            "data": CheckpointRef(
                checkpoint_id=f"cp_{index}",
                run_id="run_A",
                adapter="langgraph",
                runtime_version="1.2.14",
                agent_version="1",
                tool_versions={},
                locator={"checkpoint_id": str(index)},
            ),
        }
        with SQLiteEventStore(path) as writer:
            first = writer.append_next(draft)
            assert writer.append_next(draft) == first
            return first.seq

    with ThreadPoolExecutor(max_workers=4) as pool:
        allocated = list(pool.map(write, range(6)))
    assert sorted(allocated) == list(range(3, 9))
    with SQLiteEventStore(path) as store:
        assert [event.seq for event in store.events("run_A")] == list(range(1, 9))
        assert len(store.get_view("run_A").checkpoints) == 6


def test_branch_requires_persisted_parent_checkpoint_and_inherited_spans(
    run_record, make_event, tmp_path
):
    span = Span(
        span_id="s_A",
        run_id="run_A",
        kind="model",
        logical_node_id="model",
        call_index=1,
        started_at=run_record.created_at,
    )
    checkpoint = CheckpointRef(
        checkpoint_id="cp_A",
        run_id="run_A",
        adapter="langgraph",
        runtime_version="1.2.14",
        agent_version="1",
        tool_versions={},
        locator={},
    )
    with SQLiteEventStore(tmp_path / "runs.sqlite") as store:
        for event in [
            make_event(1, "run.created", run_record),
            make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
            make_event(3, "span.started", span, span_id=span.span_id),
            make_event(
                4,
                "span.finished",
                span.model_copy(
                    update={
                        "status": "succeeded",
                        "ended_at": span.started_at,
                    }
                ),
                span_id=span.span_id,
            ),
            make_event(5, "checkpoint.saved", checkpoint),
        ]:
            store.append(event)
        old = store.events("run_A")
        branch = Run.model_validate(
            {
                **run_record.model_dump(),
                "run_id": "run_B",
                "parent_run_id": "run_A",
                "source_checkpoint_id": "cp_A",
                "inherited_span_ids": ["s_A"],
            }
        )
        store.append(make_event(1, "run.created", branch, run_id="run_B", event_id="evt_B_1"))
        assert store.get_view("run_B").spans == ()
        assert store.events("run_A") == old
        invalid = branch.model_copy(update={"run_id": "run_C", "source_checkpoint_id": "missing"})
        with pytest.raises(ValueError, match="checkpoint_missing"):
            store.append(make_event(1, "run.created", invalid, run_id="run_C", event_id="evt_C_1"))
        assert store.run_ids() == ("run_A", "run_B")


def test_content_addressed_artifacts_survive_restart_and_detect_corruption(tmp_path):
    path = tmp_path / "runs.sqlite"
    content = "虚构实验材料".encode()
    with SQLiteEventStore(path) as store:
        first = store.put_artifact(content, media_type="text/plain", source="fixture")
        second = store.put_artifact(content, media_type="text/plain", source="fixture-copy")
        assert first.artifact_id != second.artifact_id
        assert first.sha256 == second.sha256
        assert not first.exportable
        files = list(store.artifact_root.rglob("*"))
        assert len([file for file in files if file.is_file()]) == 1
    with SQLiteEventStore(path) as reopened:
        assert reopened.get_artifact(first.artifact_id) == first
        assert reopened.read_artifact(second.artifact_id) == content
        blob = reopened.artifact_root / first.sha256[:2] / first.sha256[2:]
        blob.write_bytes(b"corrupted")
        with pytest.raises(ValueError, match="artifact_content_corrupt"):
            reopened.read_artifact(first.artifact_id)
        with pytest.raises(ValueError, match="artifact_content_corrupt"):
            reopened.put_artifact(content, media_type="text/plain", source="fixture")


def test_future_database_schema_is_not_silently_reused(tmp_path):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="unsupported_database_schema_version"):
        SQLiteEventStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999


def test_database_rejects_event_overwrite_and_delete(run_record, make_event, tmp_path):
    path = tmp_path / "runs.sqlite"
    with SQLiteEventStore(path) as store:
        store.append(make_event(1, "run.created", run_record))
        original = store.events("run_A")
        for statement in ["UPDATE events SET body='{}'", "DELETE FROM events"]:
            with sqlite3.connect(path) as connection:
                with pytest.raises(sqlite3.IntegrityError, match="events_append_only"):
                    connection.execute(statement)
        assert store.events("run_A") == original


@pytest.mark.parametrize("ending", ["cancelled", "interrupted"])
def test_inflight_call_is_readable_after_restart_without_being_reissued(
    run_record, make_event, tmp_path, ending
):
    path = tmp_path / "runs.sqlite"
    span = Span(
        span_id="inflight",
        run_id="run_A",
        kind="model",
        logical_node_id="model",
        call_index=1,
        started_at=run_record.created_at,
    )
    with SQLiteEventStore(path) as store:
        for event in [
            make_event(1, "run.created", run_record),
            make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
            make_event(3, "span.started", span, span_id=span.span_id),
        ]:
            store.append(event)
        if ending == "cancelled":
            store.append(
                make_event(
                    4,
                    "run.status_changed",
                    {
                        "before": "running",
                        "after": "cancel_requested",
                    },
                )
            )
            result = span.model_copy(
                update={
                    "status": "succeeded",
                    "ended_at": span.started_at,
                    "usage": Usage(prompt_tokens=2, completion_tokens=1, total_tokens=3),
                }
            )
            store.append(make_event(5, "span.finished", result, span_id=span.span_id))
            store.append(
                make_event(
                    6,
                    "run.status_changed",
                    {
                        "before": "cancel_requested",
                        "after": "cancelled",
                    },
                )
            )
    with SQLiteEventStore(path) as reopened:
        if ending == "interrupted":
            # Only the worker/service can decide an owner has disappeared; opening the DB cannot.
            assert reopened.get_view("run_A").run.status == "running"
            reopened.append(
                make_event(
                    4,
                    "run.status_changed",
                    {
                        "before": "running",
                        "after": "interrupted",
                        "reason": "worker_exit_observed",
                    },
                )
            )
        view = reopened.get_view("run_A")
        assert view.run.status == ending
        assert len(view.spans) == 1
        assert view.spans[0].usage.total_tokens == (3 if ending == "cancelled" else None)
        assert reopened.rebuild_view("run_A") == view


def test_actual_cost_requires_readable_evidence_before_commit(run_record, make_event, tmp_path):
    span = Span(
        span_id="s1",
        run_id="run_A",
        kind="model",
        logical_node_id="model",
        call_index=1,
        started_at=run_record.created_at,
    )
    result = span.model_copy(
        update={
            "status": "succeeded",
            "ended_at": span.started_at,
            "cost": Cost(
                kind="actual", amount="0.01", currency="CNY", evidence_artifact_id="bill_1"
            ),
        }
    )
    with SQLiteEventStore(tmp_path / "runs.sqlite") as store:
        for event in [
            make_event(1, "run.created", run_record),
            make_event(2, "run.status_changed", {"before": "queued", "after": "running"}),
            make_event(3, "span.started", span, span_id=span.span_id),
        ]:
            store.append(event)
        finish = make_event(4, "span.finished", result, span_id=span.span_id)
        with pytest.raises(KeyError):
            store.append(finish)
        assert store.get_view("run_A").last_seq == 3
        store.put_artifact(
            b"explicitly synthetic invoice fixture",
            media_type="text/plain",
            source="synthetic-test",
            artifact_id="bill_1",
        )
        store.append(finish)
        assert store.get_view("run_A").spans[0].cost.kind == "actual"


def test_committed_events_survive_worker_exit_without_cleanup(run_record, make_event, tmp_path):
    path = tmp_path / "runs.sqlite"
    with SQLiteEventStore(path) as store:
        store.append(make_event(1, "run.created", run_record))
    worker = """
import os, sys
from datetime import UTC, datetime
from agenttinker.core.records import Span
from agenttinker.storage.sqlite import SQLiteEventStore
store = SQLiteEventStore(sys.argv[1])
now = datetime.now(UTC)
store.append_next({
    'event_id': 'worker_started', 'run_id': 'run_A', 'occurred_at': now,
    'type': 'run.status_changed', 'data': {'before': 'queued', 'after': 'running'},
})
store.append_next({
    'event_id': 'call_started', 'run_id': 'run_A', 'occurred_at': now,
    'type': 'span.started', 'span_id': 'inflight',
    'data': Span(span_id='inflight', run_id='run_A', kind='model', logical_node_id='model',
                 call_index=1, started_at=now),
})
os._exit(73)
"""
    result = subprocess.run(
        [sys.executable, "-c", worker, str(path)], capture_output=True, timeout=10
    )
    assert result.returncode == 73, result.stderr.decode()
    with SQLiteEventStore(path) as reopened:
        assert reopened.get_view("run_A").last_seq == 3
        assert reopened.get_view("run_A").spans[0].status == "running"
        reopened.append(
            make_event(
                4,
                "run.status_changed",
                {
                    "before": "running",
                    "after": "interrupted",
                    "reason": "worker_exit_73_observed",
                },
            )
        )
        view = reopened.rebuild_view("run_A")
        assert view.run.status == "interrupted"
        assert len(view.spans) == 1
        assert view.spans[0].status == "interrupted"
        assert view.spans[0].usage.total_tokens is None
