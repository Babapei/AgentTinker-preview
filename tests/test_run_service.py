import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from agenttinker.m0.accounting import PriceBook
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.runtime.service import RunRequest, RunService
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore

USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 2,
    "total_tokens": 12,
    "prompt_cache_hit_tokens": 4,
    "prompt_cache_miss_tokens": 6,
}


class MeteredSynthetic(SyntheticModel):
    def __init__(self):
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return (
            super()
            .complete(messages)
            .model_copy(
                update={
                    "model": "deepseek-flash",
                    "usage": USAGE,
                    "raw_response": {"source": "offline_fixture", "usage": USAGE},
                }
            )
        )


@pytest.mark.parametrize("retry_limit,expected,attempts", [(0, "failed", 1), (1, "succeeded", 2)])
def test_langgraph_execution_persists_actual_calls_and_retry_facts(
    tmp_path, retry_limit, expected, attempts
):
    model = MeteredSynthetic()
    price = PriceBook.model_validate_json(
        (Path(__file__).parents[1] / "examples/m0/pricing-deepseek-flash-peak.json").read_text()
    ).model_copy(update={"provider": "synthetic"})
    path = tmp_path / "runs.sqlite"
    with RunService(path, model_factory=lambda _: model, pricing=price) as service:
        run, created = service.submit(
            RunRequest(mode="synthetic", policy={"tool_retry_limit": retry_limit}), "run"
        )
        view = service.wait(run.run.run_id)
        assert created and view.run.status == expected
        assert len([s for s in view.spans if s.kind == "tool"]) == attempts
        assert len(view.checkpoints) == 1
        assert view.run.capabilities.fork_from_checkpoint
        assert view.run.capabilities.patch_tool_policy
        assert view.run.config.price_version == price.version
        assert model.calls == (1 if retry_limit == 0 else 2)
        assert all(s.usage.total_tokens == 12 for s in view.spans if s.kind == "model")
        assert all(str(s.cost.amount) == "0.000004224" for s in view.spans if s.kind == "model")
    with SQLiteEventStore(path) as store:
        events = store.events(view.run.run_id)
        assert [e.seq for e in events] == list(range(1, len(events) + 1))
        failures = [e for e in events if e.type == "tool.attempt_failed"]
        assert len(failures) == 1 and failures[0].data.origin == "injected"
        assert len([e for e in events if e.type == "tool.retry_scheduled"]) == retry_limit
        assert store.rebuild_view(view.run.run_id) == view


@pytest.mark.parametrize("blocked_call", [1, 2], ids=["initial_model", "answer_model"])
def test_cancel_preserves_inflight_usage_and_stops_following_calls(tmp_path, blocked_call):
    entered, release = Event(), Event()

    class Gated(MeteredSynthetic):
        def complete(self, messages):
            if self.calls + 1 == blocked_call:
                entered.set()
                assert release.wait(5)
            return super().complete(messages)

    model = Gated()
    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: model) as service:
        try:
            run, _ = service.submit(RunRequest(mode="synthetic", inject_timeout=False), "cancel")
            run_id = run.run.run_id
            assert entered.wait(3)
            requested = service.cancel(run_id)
            assert requested.run.status == "cancel_requested"
            assert requested.spans[-1].status == "running"
            assert service.cancel(run_id) == requested
        finally:
            release.set()
        final = service.wait(run_id)
        assert final.run.status == "cancelled"
        assert model.calls == blocked_call
        assert final.spans[-1].status == "succeeded"
        assert final.spans[-1].usage.total_tokens == 12
        assert service.cancel(run_id) == final
        assert len([s for s in final.spans if s.kind == "tool"]) == (0 if blocked_call == 1 else 1)


def test_cancel_queued_run_never_constructs_its_model(tmp_path):
    entered, release = Event(), Event()
    constructed = []

    class Gated(SyntheticModel):
        def complete(self, messages):
            entered.set()
            assert release.wait(5)
            return super().complete(messages)

    def factory(request):
        constructed.append(request.task)
        return Gated()

    with RunService(tmp_path / "runs.sqlite", model_factory=factory, max_workers=1) as service:
        try:
            a, _ = service.submit(RunRequest(mode="synthetic", task="A"), "A")
            assert entered.wait(3)
            b, _ = service.submit(RunRequest(mode="synthetic", task="B"), "B")
            cancelled = service.cancel(b.run.run_id)
            assert cancelled.run.status == "cancelled"
            assert cancelled.spans == ()
        finally:
            release.set()
        service.wait(a.run.run_id)
        assert service.wait(b.run.run_id).run.status == "cancelled"
        assert constructed == ["A"]


def test_cancelling_inflight_tool_does_not_schedule_retry(tmp_path):
    entered, release = Event(), Event()
    model = MeteredSynthetic()

    def tool(query, top_k):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("private_tool_marker")

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: model, tool=tool) as service:
        try:
            run, _ = service.submit(
                RunRequest(mode="synthetic", inject_timeout=False, policy={"tool_retry_limit": 3}),
                "tool-cancel",
            )
            assert entered.wait(3)
            service.cancel(run.run.run_id)
        finally:
            release.set()
        view = service.wait(run.run.run_id)
        assert view.run.status == "cancelled"
        assert model.calls == 1
        with SQLiteEventStore(service.database) as store:
            events = store.events(view.run.run_id)
            assert not any(e.type == "tool.retry_scheduled" for e in events)
            assert "private_tool_marker" not in "".join(e.model_dump_json() for e in events)


@pytest.mark.parametrize("protocol_error", [False, True], ids=["provider_error", "protocol_error"])
def test_failed_model_retains_only_observed_usage_and_safe_diagnostics(tmp_path, protocol_error):
    class Rejected(MeteredSynthetic):
        def complete(self, messages):
            if not protocol_error:
                raise RuntimeError("private_provider_marker")
            return super().complete(messages).model_copy(update={"choice_count": 0, "message": {}})

    with RunService(tmp_path / "runs.sqlite", model_factory=lambda _: Rejected()) as service:
        run, _ = service.submit(RunRequest(mode="synthetic"), "error")
        view = service.wait(run.run.run_id)
        assert view.run.status == "failed"
        assert len(view.spans) == 1
        assert view.spans[0].status == ("succeeded" if protocol_error else "failed")
        assert view.spans[0].usage.total_tokens == (12 if protocol_error else None)
        with SQLiteEventStore(service.database) as store:
            assert "private_provider_marker" not in "".join(
                e.model_dump_json() for e in store.events(view.run.run_id)
            )


def test_concurrent_submission_and_restart_keep_one_durable_request_identity(tmp_path):
    path = tmp_path / "runs.sqlite"
    model = MeteredSynthetic()
    request = RunRequest(mode="synthetic", inject_timeout=False)
    with RunService(path, model_factory=lambda _: model) as service:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: service.submit(request, "same-key"), range(8)))
        assert sum(created for _, created in results) == 1
        run_id = results[0][0].run.run_id
        assert {view.run.run_id for view, _ in results} == {run_id}
        assert service.wait(run_id).run.status == "succeeded"
        assert model.calls == 2
        with pytest.raises(EventConflict):
            service.submit(request.model_copy(update={"task": "different"}), "same-key")
    with RunService(
        path, model_factory=lambda _: pytest.fail("must not dispatch again")
    ) as reopened:
        saved, created = reopened.submit(request, "same-key")
        assert not created and saved.run.run_id == run_id and saved.run.status == "succeeded"


def test_owner_exclusivity_and_crashed_worker_recovery_do_not_reissue_calls(tmp_path):
    path = tmp_path / "runs.sqlite"
    script = """
import os, sys
from agenttinker.runtime.service import RunService, RunRequest
from agenttinker.m0.synthetic import SyntheticModel
class Crashed(SyntheticModel):
    def complete(self, messages):
        os._exit(73)
service = RunService(sys.argv[1], model_factory=lambda _: Crashed())
run, _ = service.submit(RunRequest(mode='synthetic'), 'crashed')
service.wait(run.run.run_id)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(path)], capture_output=True, timeout=10
    )
    assert child.returncode == 73, child.stderr.decode()
    with RunService(path, model_factory=lambda _: pytest.fail("must not reissue")) as recovered:
        with pytest.raises(RuntimeError, match="owner_already_active"):
            RunService(path)
        view, created = recovered.submit(RunRequest(mode="synthetic"), "crashed")
        assert not created and view.run.status == "interrupted"
        assert len(view.spans) == 1 and view.spans[0].status == "interrupted"
        assert view.spans[0].usage.total_tokens is None


def test_v1_database_migration_keeps_facts_and_adds_durable_request_table(
    tmp_path, run_record, make_event
):
    path = tmp_path / "legacy.sqlite"
    with SQLiteEventStore(path) as store:
        store.append(make_event(1, "run.created", run_record))
        original = store.events(run_record.run_id)
    with sqlite3.connect(path) as connection:
        for trigger in (
            "imported_runs_no_update",
            "imported_runs_no_delete",
            "imported_events_no_insert",
        ):
            connection.execute(f"DROP TRIGGER {trigger}")
        for table in (
            "import_requests",
            "import_runs",
            "imports",
            "assessment_requests",
            "reviews",
            "evaluations",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DROP TABLE run_requests")
        connection.execute("PRAGMA user_version=1")
    with SQLiteEventStore(path) as migrated:
        assert migrated.events(run_record.run_id) == original
        assert migrated.request_run("not-created", "fingerprint") is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_dispatch_failure_is_recorded_and_retry_does_not_start_again(tmp_path, monkeypatch):
    with RunService(tmp_path / "runs.sqlite") as service:

        def failed_dispatch(*args):
            raise RuntimeError("private_dispatch_marker")

        monkeypatch.setattr(service._pool, "submit", failed_dispatch)
        request = RunRequest(mode="synthetic")
        view, created = service.submit(request, "dispatch-error")
        assert created and view.run.status == "failed" and view.spans == ()
        saved, again = service.submit(request, "dispatch-error")
        assert not again and saved == view
        with SQLiteEventStore(service.database) as store:
            assert "private_dispatch_marker" not in "".join(
                e.model_dump_json() for e in store.events(view.run.run_id)
            )
