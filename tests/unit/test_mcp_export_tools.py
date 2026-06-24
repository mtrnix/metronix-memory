import pytest

import metronix.mcp.tools.export as export_tool


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
