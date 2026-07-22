from unittest.mock import AsyncMock, MagicMock

import pytest

import metronix.mcp.tools.export as export_tool
from metronix.export.models import ExportScope
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal


@pytest.mark.asyncio
async def test_export_data_requires_explicit_scope():
    res = await export_tool.metronix_export_data()
    assert "error" in res
    assert res["error"]["code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_export_data_starts_job(monkeypatch):
    class FakeJob:
        id = "exp9"
        status = "pending"

    class FakeSvc:
        async def start(self, scope):
            assert scope.workspace_id == "ws1"
            return FakeJob()

        async def status(self, export_id):
            return {"export_id": export_id, "status": "pending", "counts": {}, "size_bytes": 0}

    monkeypatch.setattr(export_tool, "build_export_service", lambda s: FakeSvc())
    res = await export_tool.metronix_export_data(workspace_id="ws1")
    assert res["export_id"] == "exp9" and res["status"] == "pending"


@pytest.mark.asyncio
async def test_export_data_rejects_ungranted_workspace_before_creating_service(monkeypatch):
    build_service = MagicMock()
    monkeypatch.setattr(export_tool, "build_export_service", build_service)
    token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
    try:
        res = await export_tool.metronix_export_data(workspace_id="ws-b")
    finally:
        reset_principal(token)

    assert "No access to workspace 'ws-b'" in res["error"]["message"]
    build_service.assert_not_called()


@pytest.mark.asyncio
async def test_export_data_rejects_all_workspaces_without_wildcard_before_creating_service(
    monkeypatch,
):
    build_service = MagicMock()
    monkeypatch.setattr(export_tool, "build_export_service", build_service)
    token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
    try:
        res = await export_tool.metronix_export_data(all_workspaces=True)
    finally:
        reset_principal(token)

    assert "all_workspaces requires admin access" in res["error"]["message"]
    build_service.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [ExportScope(workspace_id="ws-b"), ExportScope(all_workspaces=True)],
)
async def test_export_status_rejects_ungranted_scope_before_returning_download_url(
    monkeypatch,
    scope,
):
    service = AsyncMock()
    service.get_job = AsyncMock(return_value=MagicMock(scope=scope))
    service.status = AsyncMock(return_value={"download_url": "https://example.test/secret.zip"})
    monkeypatch.setattr(export_tool, "build_export_service", lambda s: service)
    token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
    try:
        res = await export_tool.metronix_export_status("export-foreign")
    finally:
        reset_principal(token)

    assert "no access to this export" in res["error"]["message"]
    service.status.assert_not_awaited()
