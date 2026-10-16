import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_run_service import MeteredSynthetic

from agenttinker.core.projection import project_events
from agenttinker.core.records import Capabilities
from agenttinker.m0.fixtures import search_documents
from agenttinker.runtime.checkpoints import ForkRejected, checkpoint_path
from agenttinker.runtime.service import ForkRequest, RunRequest, RunService
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore


def fork_request(view, patch=None):
    return ForkRequest(
        source_checkpoint_id=view.checkpoints[0].checkpoint_id,
        patch=patch if patch is not None else {"tool_retry_limit": 1},
    )


def saver_rows(database):
    with sqlite3.connect(checkpoint_path(database)) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("checkpoints", "writes")
        }


def test_restart_fork_reuses_prefix_preserves_all_old_facts_and_repeats_first_fault(tmp_path):
    database = tmp_path / "runs.sqlite"
    model = MeteredSynthetic()
    with RunService(database, model_factory=lambda _: model) as service:
        a, _ = service.submit(RunRequest(mode="synthetic"), "A")
        a = service.wait(a.run.run_id)
        assert model.calls == 1 and a.run.status == "failed"
    old_states = saver_rows(database)
    with SQLiteEventStore(database) as store:
        old_events = store.events(a.run.run_id)
    model = MeteredSynthetic()
    with RunService(database, model_factory=lambda _: model) as service:
        b, created = service.fork(a.run.run_id, fork_request(a), "B")
        b = service.wait(b.run.run_id)
        assert created and b.run.status == "succeeded" and model.calls == 1
        assert b.run.parent_run_id == a.run.run_id
        assert b.run.source_checkpoint_id == a.checkpoints[0].checkpoint_id
        assert b.run.inherited_span_ids == (a.spans[0].span_id,)
        assert sum(span.usage.total_tokens or 0 for span in b.spans) == 12
        assert (
            b.run.config.model_copy(update={"tool_policy": a.run.config.tool_policy})
            == a.run.config
        )
        assert b.run.intervention.before == a.run.config.tool_policy
        assert b.run.intervention.after == b.run.config.tool_policy
        assert b.run.intervention.patch == {"tool_retry_limit": 1}
        tools = [span for span in b.spans if span.kind == "tool"]
        assert [span.attempt for span in tools] == [1, 2]
        assert tools[0].output == a.spans[-1].output
        assert all(span.parent_span_id == a.spans[0].span_id for span in tools)
        assert all(span.logical_call_id == a.spans[-1].logical_call_id for span in tools)
        assert all(span.input["tool_call"] == a.spans[-1].input["tool_call"] for span in tools)
        assert all(
            span.input["intervention_id"] == b.run.intervention.intervention_id for span in tools
        )
        assert service.checkpoint_availability(b.run.run_id)[0].available
        # Fork again from B's before-tool point, still referencing only A's model prefix.
        c, _ = service.fork(b.run.run_id, fork_request(b, {"top_k": 3}), "C")
        c = service.wait(c.run.run_id)
        assert c.run.status == "succeeded" and model.calls == 2
        assert c.run.inherited_span_ids == b.run.inherited_span_ids
        assert len([span for span in c.spans if span.kind == "model"]) == 1
        assert service.get(a.run.run_id) == a and service.get(b.run.run_id) == b
    new_states = saver_rows(database)
    original_checkpoint_ids = {row[2] for row in old_states["checkpoints"]}
    for table in old_states:
        assert [
            row for row in new_states[table] if row[2] in original_checkpoint_ids
        ] == old_states[table]
    with SQLiteEventStore(database) as store:
        assert store.events(a.run.run_id) == old_events
        assert store.get_view(a.run.run_id) == a
        assert project_events(store.events(b.run.run_id)) == b
        assert project_events(store.events(c.run.run_id)) == c


def test_top_k_fork_after_success_reruns_tool_and_only_the_answer_model(tmp_path):
    model, queries = MeteredSynthetic(), []

    def tool(query, top_k):
        queries.append((query, top_k))
        return search_documents(query, top_k)

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: model, tool=tool) as service:
        a, _ = service.submit(RunRequest(mode="synthetic", inject_timeout=False), "A")
        a = service.wait(a.run.run_id)
        b, _ = service.fork(a.run.run_id, fork_request(a, {"top_k": 3}), "B")
        b = service.wait(b.run.run_id)
        assert a.run.status == b.run.status == "succeeded"
        assert model.calls == 3
        assert queries == [("release", 2), ("release", 3)]
        assert len(b.spans[0].output["documents"]) == 3
        assert b.spans[1].input["messages"][:3] == a.spans[-1].input["messages"][:3]
        assert service.get(a.run.run_id) == a


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"tool_retry_limit": 0},
        {"tool_retry_limit": 1, "top_k": 3},
        {"query": "changed"},
        {"tool_retry_limit": True},
        {"tool_retry_limit": "1"},
        {"tool_retry_limit": -1},
        {"tool_retry_limit": 4},
        {"top_k": 0},
        {"top_k": 4},
    ],
)
def test_invalid_patch_never_creates_or_executes_a_branch(tmp_path, patch):
    model = MeteredSynthetic()
    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: model) as service:
        a, _ = service.submit(RunRequest(mode="synthetic"), "A")
        a = service.wait(a.run.run_id)
        with pytest.raises(ForkRejected, match="invalid_patch"):
            service.fork(a.run.run_id, fork_request(a, patch), "B")
        with SQLiteEventStore(service.database) as store:
            assert store.run_ids() == (a.run.run_id,)
        assert model.calls == 1 and service.get(a.run.run_id) == a


def test_fork_idempotency_is_atomic_concurrent_and_survives_restart_with_missing_saver(tmp_path):
    database, model = tmp_path / "runs.sqlite", MeteredSynthetic()
    with RunService(database, model_factory=lambda _: model) as service:
        a, _ = service.submit(RunRequest(mode="synthetic"), "A")
        a = service.wait(a.run.run_id)
        request = fork_request(a)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: service.fork(a.run.run_id, request, "B"), range(8)))
        assert sum(created for _, created in results) == 1
        assert len({view.run.run_id for view, _ in results}) == 1
        b = service.wait(results[0][0].run.run_id)
        assert model.calls == 2
        with pytest.raises(EventConflict):
            service.fork(a.run.run_id, fork_request(a, {"top_k": 3}), "B")
        with pytest.raises(EventConflict):
            service.submit(RunRequest(mode="synthetic"), "B")
    checkpoint_path(database).unlink()
    with RunService(database, model_factory=lambda _: pytest.fail("duplicate dispatch")) as service:
        duplicate, created = service.fork(a.run.run_id, request, "B")
        assert not created and duplicate == b
        availability = service.checkpoint_availability(a.run.run_id)[0]
        assert not availability.available and availability.reason == "checkpoint_missing"
        assert availability.allowed_patch_fields == ()
        with pytest.raises(ForkRejected, match="checkpoint_missing"):
            service.fork(a.run.run_id, request, "new")
        assert not checkpoint_path(database).exists()
        assert service.get(a.run.run_id) == a


def test_source_must_finish_and_cancelled_queued_branch_does_not_build_model(tmp_path):
    entered, release = Event(), Event()
    model, constructed = MeteredSynthetic(), []

    def tool(query, top_k):
        entered.set()
        assert release.wait(5)
        return search_documents(query, top_k)

    def factory(request):
        constructed.append(request.task)
        return model

    with RunService(
        tmp_path / "runs.sqlite", model_factory=factory, tool=tool, max_workers=1
    ) as service:
        try:
            a, _ = service.submit(RunRequest(mode="synthetic", inject_timeout=False), "A")
            assert entered.wait(3)
            active = service.get(a.run.run_id)
            assert (
                service.checkpoint_availability(active.run.run_id)[0].reason == "source_run_active"
            )
            with pytest.raises(ForkRejected, match="source_run_active"):
                service.fork(active.run.run_id, fork_request(active), "invalid")
        finally:
            release.set()
        a = service.wait(a.run.run_id)
        entered.clear()
        release.clear()
        try:
            blocker, _ = service.submit(
                RunRequest(mode="synthetic", inject_timeout=False, task="blocker"), "blocker"
            )
            assert entered.wait(3)
            b, _ = service.fork(a.run.run_id, fork_request(a, {"top_k": 3}), "B")
            assert service.cancel(b.run.run_id).run.status == "cancelled"
        finally:
            release.set()
        service.wait(blocker.run.run_id)
        b = service.wait(b.run.run_id)
        assert b.spans == () and b.checkpoints == ()
        assert constructed == [a.run.config.task, "blocker"]


def test_legacy_run_keeps_unsupported_capability_and_readable_history(tmp_path):
    from datetime import UTC, datetime

    from agenttinker.core.records import CheckpointRef, Run, RunConfig, VersionRef

    database = tmp_path / "runs.sqlite"
    now = datetime.now(UTC)
    run = Run(
        run_id="legacy",
        mode="synthetic",
        created_at=now,
        updated_at=now,
        config=RunConfig(agent=VersionRef(id="serial-checkpoint", version="1")),
        capabilities=Capabilities(run_from_start=True),
    )
    with SQLiteEventStore(database) as store:
        store.create_requested_run(run, "legacy", "fingerprint")
        store.append_next(
            {
                "event_id": "running",
                "run_id": run.run_id,
                "occurred_at": now,
                "type": "run.status_changed",
                "data": {"before": "queued", "after": "running"},
            }
        )
        store.append_next(
            {
                "event_id": "checkpoint",
                "run_id": run.run_id,
                "occurred_at": now,
                "type": "checkpoint.saved",
                "data": CheckpointRef(
                    checkpoint_id="old_cp",
                    run_id=run.run_id,
                    adapter="langgraph",
                    runtime_version="1.2.14",
                    agent_version="1",
                    tool_versions={},
                    locator={},
                ),
            }
        )
    with RunService(database) as service:
        old = service.get(run.run_id)
        assert old.run.status == "interrupted"
        assert not old.run.capabilities.fork_from_checkpoint
        assert service.checkpoint_availability(run.run_id)[0].reason == "unsupported_capability"
        with pytest.raises(ForkRejected, match="unsupported_capability"):
            service.fork(run.run_id, fork_request(old), "B")
        assert service.get(run.run_id) == old
