"""Temporary native synthetic history for browser integration; never uses live keys."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

import uvicorn

from agenttinker.api.app import create_app
from agenttinker.m0.synthetic import SyntheticModel
from agenttinker.runtime.service import RunRequest, RunService
from agenttinker.storage.sqlite import SQLiteEventStore


def no_execution(_request):
    raise AssertionError("browser_history_must_not_execute")


def test_app(database):
    gates = {}

    class Gated(SyntheticModel):
        def __init__(self, entered, release):
            self.entered, self.release, self.calls = entered, release, 0

        def complete(self, messages):
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                if not self.release.wait(10):
                    raise TimeoutError("offline_browser_gate")
            return super().complete(messages)

    def factory(request):
        if request.mode != "synthetic" or request.task not in gates:
            return no_execution(request)
        return Gated(*gates[request.task])

    def service_factory(path, **kwargs):
        return RunService(path, model_factory=factory, **kwargs)

    app = create_app(database, service_factory=service_factory, poll_interval=0.02)

    # These driver endpoints exist only in this temporary test server, never the app factory.
    @app.post("/__test__/runs")
    def start_fixture():
        task = f"浏览器实时模拟 {uuid4().hex}"
        entered, release = Event(), Event()
        gates[task] = entered, release
        view, _ = app.state.service.submit(
            RunRequest(mode="synthetic", task=task, policy={"tool_retry_limit": 1}), task
        )
        if not entered.wait(3):
            raise TimeoutError("offline_browser_start")
        return {"run_id": view.run.run_id}

    @app.post("/__test__/runs/{run_id}/release")
    def release_fixture(run_id: str):
        task = app.state.service.get(run_id).run.config.task
        gates[task][1].set()
        return {"released": True}

    @app.get("/__test__/runs/{run_id}/events")
    def fixture_facts(run_id: str):
        with SQLiteEventStore(database) as store:
            return [event.model_dump(mode="json") for event in store.events(run_id)]

    return app


def main():
    with TemporaryDirectory(prefix="agenttinker-web-") as directory:
        database = Path(directory) / "runs.sqlite"
        with RunService(database) as service:
            for limit, task in ((0, "基线：首次检索超时"), (1, "重试：比较虚构发布说明")):
                view, _ = service.submit(
                    RunRequest(mode="synthetic", task=task, policy={"tool_retry_limit": limit}),
                    f"browser-fixture-{limit}",
                )
                service.wait(view.run.run_id)
        uvicorn.run(
            test_app(database),
            host="127.0.0.1",
            port=8000,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
