import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.export.jobs import ExportJobStore
from metronix.export.models import ExportJob, ExportScope, ExportStatus

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_get_update_dedup():
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    store = ExportJobStore(engine)
    scope = ExportScope(workspace_id="ws_test_export")
    job = ExportJob(id="exp-test-1", scope=scope, status=ExportStatus.PENDING)

    await store.create(job)
    got = await store.get("exp-test-1")
    assert got is not None and got.status == ExportStatus.PENDING and got.scope == scope

    active = await store.find_active_for_scope(scope)
    assert active is not None and active.id == "exp-test-1"

    await store.set_status("exp-test-1", ExportStatus.RUNNING)
    await store.set_result(
        "exp-test-1",
        workspace_count=1,
        agent_count=2,
        memory_record_count=5,
        document_count=3,
        size_bytes=999,
        archive_path="/app/data/exports/exp-test-1.zip",
        download_token="tok-test-1",
    )
    await store.set_status("exp-test-1", ExportStatus.READY)
    done = await store.get("exp-test-1")
    assert done.status == ExportStatus.READY and done.size_bytes == 999
    assert await store.find_active_for_scope(scope) is None  # ready != active
