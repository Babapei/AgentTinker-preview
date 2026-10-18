"""Optional built UI shares the runtime origin without changing its API or execution."""

import sys

import pytest
from fastapi.testclient import TestClient

from agenttinker.api import cli
from agenttinker.api.app import create_app
from agenttinker.core.projection import RunView


def bundle(tmp_path):
    directory = tmp_path / "web"
    directory.mkdir()
    (directory / "index.html").write_text('<html><script src="/assets/main.js"></script></html>')
    (directory / "assets").mkdir()
    (directory / "assets" / "main.js").write_text("console.log('local build')")
    return directory


def test_web_origin_serves_assets_and_preserves_api_docs_control_and_sse(tmp_path):
    database = tmp_path / "runs.sqlite"
    web_dist = bundle(tmp_path)
    with TestClient(create_app(database, web_dist=web_dist)) as client:
        assert client.get("/").text == client.get("/?run=not-selected-yet").text
        assert client.get("/assets/main.js").text == "console.log('local build')"
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").json()["info"]["title"] == "AgentTinker local runtime"
        assert client.get("/api/v1/scenarios").json()[0]["agent"]["ref"]["version"] == "2"
        assert client.get("/api/v1/not-a-route").status_code == 404
        assert "<html>" not in client.get("/api/v1/not-a-route").text
        assert client.get("/api/v1/runs").json()["total"] == 0
        response = client.post(
            "/api/v1/runs", json={"mode": "synthetic"}, headers={"Idempotency-Key": "A"}
        )
        assert response.status_code == 201
        run_id = response.json()["run"]["run_id"]
        view = client.app.state.service.wait(run_id)
        assert RunView.model_validate(client.get(f"/api/v1/runs/{run_id}").json()) == view
        stream = client.get(f"/api/v1/runs/{run_id}/events")
        assert "text/event-stream" in stream.headers["content-type"]
        assert "event: run.status_changed" in stream.text
    with TestClient(create_app(database)) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/v1/runs").json()["total"] == 1


@pytest.mark.parametrize("defect", ["missing", "file", "no_index", "index_escape"])
def test_invalid_build_rejects_before_service_or_database_creation(tmp_path, defect):
    web_dist = tmp_path / "web"
    if defect == "file":
        web_dist.write_text("not a directory")
    elif defect != "missing":
        web_dist.mkdir()
        if defect == "index_escape":
            outside = tmp_path / "outside.html"
            outside.write_text("not part of the build")
            (web_dist / "index.html").symlink_to(outside)
    database = tmp_path / "never-created.sqlite"
    with pytest.raises(ValueError, match="web_build_missing"):
        create_app(
            database,
            web_dist=web_dist,
            service_factory=lambda *args, **kwargs: pytest.fail("invalid build started runtime"),
        )
    assert not database.exists()


def test_static_paths_and_symlinks_cannot_read_outside_the_selected_bundle(tmp_path):
    web_dist = bundle(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside the selected build")
    (web_dist / "assets" / "escape.txt").symlink_to(outside)
    with TestClient(create_app(tmp_path / "runs.sqlite", web_dist=web_dist)) as client:
        for path in [
            "/assets/escape.txt",
            "/%2e%2e/outside.txt",
            "/assets/%2e%2e/%2e%2e/outside.txt",
        ]:
            response = client.get(path)
            assert response.status_code == 404
            assert outside.read_text() not in response.text


def test_cli_reports_missing_build_without_binding_or_creating_a_database(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "never-created.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agenttinker-server",
            "--database",
            str(database),
            "--web-dist",
            str(tmp_path / "missing"),
        ],
    )
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda *a, **kw: pytest.fail("invalid build bound server")
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert "web_build_missing" in capsys.readouterr().err
    assert not database.exists()
