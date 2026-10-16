"""Temporary native synthetic history for browser integration; never uses live keys."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from agenttinker.api.app import create_app
from agenttinker.runtime.service import RunRequest, RunService


def no_execution(_request):
    raise AssertionError("browser_history_must_not_execute")


def history_service(database, **kwargs):
    return RunService(database, model_factory=no_execution, **kwargs)


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
            create_app(database, service_factory=history_service),
            host="127.0.0.1",
            port=8000,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
