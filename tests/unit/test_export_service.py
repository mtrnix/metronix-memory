import zipfile
from datetime import UTC, datetime

import pytest

from metronix.core.models import MemoryRecord, RawDocument
from metronix.export.models import ExportScope, ExportStatus
from metronix.export.service import ExportService


class FakeMemory:
    async def list_workspaces(self):
        return ["ws1"]

    async def list_agent_ids(self, ws):
        return ["agent/one", "ghost"]

    async def list_records(self, ws, *, agent_id, lifetime, limit, offset):
        if offset > 0:
            return []
        return [MemoryRecord(workspace_id=ws, agent_id=agent_id, content=f"m-{agent_id}")]


class FakeDocs:
    async def list_document_workspaces(self):
        return ["ws1"]

    async def list_raw_documents_keyset(self, ws, *, after_updated_at, after_id, limit):
        if after_id is not None:
            return []
        return [
            RawDocument(
                id="d1",
                workspace_id=ws,
                connector_type="jira",
                source_id="PROJ-1",
                content="body",
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]


class FakeRegistry:
    async def registered_agent_ids(self, ws):
        return {"agent/one"}  # 'ghost' is unregistered


class FakeJobs:
    def __init__(self):
        self.jobs = {}

    async def create(self, job):
        self.jobs[job.id] = job

    async def get(self, export_id):
        return self.jobs.get(export_id)

    async def set_status(self, export_id, status, *, error=None):
        self.jobs[export_id].status = status
        self.jobs[export_id].error = error

    async def set_result(self, export_id, **kw):
        j = self.jobs[export_id]
        for k, v in kw.items():
            setattr(j, k, v)

    async def find_active_for_scope(self, scope):
        for j in self.jobs.values():
            if j.scope.key() == scope.key() and j.status in (
                ExportStatus.PENDING,
                ExportStatus.RUNNING,
            ):
                return j
        return None


class FakeTokens:
    async def mint(self, export_id, path):
        return "tok-123"


def _service(tmp_path, jobs):
    return ExportService(
        memory=FakeMemory(),
        docs=FakeDocs(),
        registry=FakeRegistry(),
        job_store=jobs,
        token_store=FakeTokens(),
        archive_dir=str(tmp_path),
        public_base_url="http://host:8001",
        disk_cap_bytes=10_000_000,
        new_id=lambda: "exp1",
        now=lambda: datetime(2026, 6, 24, tzinfo=UTC),
        schedule=lambda coro: coro.close(),  # no background build in tests
    )


@pytest.mark.asyncio
async def test_build_produces_zip_with_all_agents_and_docs(tmp_path):
    jobs = FakeJobs()
    svc = _service(tmp_path, jobs)
    scope = ExportScope(workspace_id="ws1")
    job = await svc.start(scope)
    await svc._build(job.id, scope)  # run synchronously for assertion

    done = await jobs.get(job.id)
    assert done.status == ExportStatus.READY
    assert done.agent_count == 2 and done.document_count == 1

    with zipfile.ZipFile(done.archive_path) as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert any(n.startswith("ws1/memory/") for n in names)
        assert any(n.startswith("ws1/documents/jira/") for n in names)
        manifest = z.read("manifest.json").decode()
    assert "ghost" in manifest  # unregistered agent included


@pytest.mark.asyncio
async def test_status_returns_download_url_when_ready(tmp_path):
    jobs = FakeJobs()
    svc = _service(tmp_path, jobs)
    scope = ExportScope(workspace_id="ws1")
    job = await svc.start(scope)
    await svc._build(job.id, scope)
    st = await svc.status(job.id)
    assert st["status"] == "ready"
    assert st["download_url"] == ("http://host:8001/api/v1/export/exp1/download?token=tok-123")


@pytest.mark.asyncio
async def test_dedup_returns_existing_active_job(tmp_path):
    jobs = FakeJobs()
    svc = _service(tmp_path, jobs)
    scope = ExportScope(workspace_id="ws1")
    j1 = await svc.start(scope)
    j2 = await svc.start(scope)  # active job exists -> returns same
    assert j1.id == j2.id
