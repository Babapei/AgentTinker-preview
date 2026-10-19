"""Preview protection covers the complete origin without altering native runs."""

import sys

import pytest
from fastapi.testclient import TestClient

from agenttinker.api import cli
from agenttinker.api.app import create_app


def test_preview_protects_page_api_docs_mutations_and_streams(tmp_path):
    password = "offline-preview-password"
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>protected preview</html>")
    app = create_app(tmp_path / "runs.sqlite", web_dist=web, access_password=password)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        for path in ["/", "/docs", "/openapi.json", "/api/v1/runs", "/api/v1/runs/x/events"]:
            response = client.get(path)
            assert response.status_code == 401
            assert response.headers["www-authenticate"].startswith("Basic ")
            assert password not in response.text
        for headers in [
            {"Authorization": "Basic !!!"},
            {"Authorization": b"Basic \xe9"},
            {"Authorization": "Bearer incorrect"},
        ]:
            # HTTP header values are Latin-1; malformed credentials must still be 401.
            response = client.get("/api/v1/runs", headers=headers)
            assert response.status_code == 401
        assert client.get("/", auth=("wrong", password)).status_code == 401
        assert client.get("/", auth=("preview", "wrong-password")).status_code == 401
        response = client.post(
            "/api/v1/runs",
            json={"mode": "synthetic"},
            headers={"Idempotency-Key": "unauthorized"},
        )
        assert response.status_code == 401
        auth = ("preview", password)
        assert "protected preview" in client.get("/", auth=auth).text
        assert client.get("/api/v1/runs", auth=auth).json()["total"] == 0
        created = client.post(
            "/api/v1/runs",
            json={"mode": "synthetic"},
            headers={"Idempotency-Key": "authorized", "Origin": "http://testserver"},
            auth=auth,
        )
        assert created.status_code == 201
        run_id = created.json()["run"]["run_id"]
        final = app.state.service.wait(run_id)
        assert final.run.status == "failed"
        stream = client.get(f"/api/v1/runs/{run_id}/events", auth=auth)
        assert stream.status_code == 200 and "event: run.status_changed" in stream.text
        assert client.get(f"/api/v1/runs/{run_id}/events").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://another.example"},
        {"Origin": "null"},
        {"Origin": "http://testserver.attacker.example"},
        {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cross_origin_write_is_rejected_before_creating_run(tmp_path, headers):
    password = "offline-preview-password"
    app = create_app(tmp_path / "runs.sqlite", access_password=password)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            content='{"mode":"synthetic"}',
            headers={**headers, "Content-Type": "text/plain", "Idempotency-Key": "cross-site"},
            auth=("preview", password),
        )
        assert response.status_code == 403
        assert client.get("/api/v1/runs", auth=("preview", password)).json()["total"] == 0


@pytest.mark.parametrize("password", [None, "", "short"])
def test_required_preview_password_fails_before_listen_or_database(
    tmp_path, monkeypatch, capsys, password
):
    if password is None:
        monkeypatch.delenv("AGENTTINKER_ACCESS_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("AGENTTINKER_ACCESS_PASSWORD", password)
    database = tmp_path / "never-created.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        ["agenttinker-server", "--database", str(database), "--require-access-password"],
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: pytest.fail("bound without password"))
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert "access_password_" in capsys.readouterr().err
    assert not database.exists()
