"""Temporary production-build check server: no model may be constructed."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi.staticfiles import StaticFiles

from agenttinker.api.app import create_app
from agenttinker.runtime.service import RunService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="agenttinker-reference-browser-") as directory:
        attempted = []

        def denied(request):
            attempted.append(request.mode)
            raise AssertionError("reference_browser_must_not_construct_models")

        def service_factory(database, **kwargs):
            return RunService(database, model_factory=denied, **kwargs)

        app = create_app(Path(directory) / "runs.sqlite", service_factory=service_factory)

        @app.get("/__reference__/stats")
        def stats():
            return {"model_constructions": len(attempted)}

        app.mount("/", StaticFiles(directory="web/dist", html=True), name="reference-build")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
