from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from metronix.api.routes import export as export_routes
from metronix.api.routes.export import _authorize_job_access
from metronix.export.models import ExportScope


class FakeSvc:
    async def start(self, scope):
        return SimpleNamespace(id="exp1", status="pending")

    async def get_job(self, export_id):
        if export_id != "exp1":
            return None
        return SimpleNamespace(id="exp1", scope=ExportScope(workspace_id="ws1"))

    async def status(self, export_id):
        if export_id != "exp1":
            return None
        return {
            "export_id": "exp1",
            "status": "ready",
            "counts": {},
            "size_bytes": 0,
            # relative — the route should absolutize it from the request host
            "download_url": "/api/v1/export/exp1/download?token=t",
        }


class FakeTokens:
    async def peek(self, token):
        if token == "goodtoken":
            return {"export_id": "exp1", "path": "/nonexistent/exp1.zip"}
        return None

    async def consume(self, token):
        if token == "goodtoken":
            return {"export_id": "exp1", "path": "/nonexistent/exp1.zip"}
        return None


def _app(user_workspaces=None):
    app = FastAPI()
    app.state.export_service = FakeSvc()
    app.state.export_token_store = FakeTokens()
    from metronix.api.dependencies import resolve_workspace_id

    app.dependency_overrides[resolve_workspace_id] = lambda: "ws1"

    if user_workspaces is not None:

        @app.middleware("http")
        async def _user(request, call_next):
            request.state.user = {"workspace_ids": user_workspaces}
            return await call_next(request)

    app.include_router(export_routes.router, prefix="/api/v1")
    return app


def test_post_export_starts():
    client = TestClient(_app())
    r = client.post("/api/v1/export", json={"workspace_id": "ws1"})
    assert r.status_code == 200 and r.json()["export_id"] == "exp1"


def test_download_unknown_token_404():
    client = TestClient(_app())
    r = client.get("/api/v1/export/exp1/download?token=badtoken")
    assert r.status_code == 404


def test_download_missing_archive_410_without_consuming():
    client = TestClient(_app())
    r = client.get("/api/v1/export/exp1/download?token=goodtoken")
    assert r.status_code == 410


def test_status_authorized_absolutizes_url():
    client = TestClient(_app(user_workspaces=["ws1"]))
    r = client.get("/api/v1/export/exp1")
    assert r.status_code == 200
    assert r.json()["download_url"] == "http://testserver/api/v1/export/exp1/download?token=t"


def test_status_foreign_workspace_403():
    client = TestClient(_app(user_workspaces=["other"]))
    r = client.get("/api/v1/export/exp1")
    assert r.status_code == 403


def test_routes_503_when_service_missing():
    app = FastAPI()  # no export_service on state
    from metronix.api.dependencies import resolve_workspace_id

    app.dependency_overrides[resolve_workspace_id] = lambda: "ws1"
    app.include_router(export_routes.router, prefix="/api/v1")
    r = TestClient(app).post("/api/v1/export", json={"workspace_id": "ws1"})
    assert r.status_code == 503


def _req(workspace_ids):
    return SimpleNamespace(state=SimpleNamespace(user={"workspace_ids": workspace_ids}))


def test_authz_allows_owning_workspace():
    _authorize_job_access(_req(["ws1"]), ExportScope(workspace_id="ws1"))  # no raise


def test_authz_denies_foreign_workspace():
    with pytest.raises(HTTPException) as exc:
        _authorize_job_access(_req(["ws2"]), ExportScope(workspace_id="ws1"))
    assert exc.value.status_code == 403


def test_authz_all_workspaces_requires_admin():
    with pytest.raises(HTTPException) as exc:
        _authorize_job_access(_req(["ws1"]), ExportScope(all_workspaces=True))
    assert exc.value.status_code == 403
    _authorize_job_access(_req(["*"]), ExportScope(all_workspaces=True))  # admin: no raise
