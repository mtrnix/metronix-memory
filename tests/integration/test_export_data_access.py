import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.storage.memory_postgres import MemoryPostgresStore
from metronix.storage.postgres import PostgresStore

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_list_agent_ids_distinct():
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    store = MemoryPostgresStore(engine)
    ids = await store.list_agent_ids("nonexistent-ws")
    assert ids == []  # no rows, but method exists and returns a list


@pytest.mark.asyncio
async def test_doc_keyset_first_page_runs():
    store = PostgresStore(Settings().postgres_dsn)
    try:
        page = await store.list_raw_documents_keyset(
            "nonexistent-ws", after_updated_at=None, after_id=None, limit=10
        )
        assert page == []
        assert isinstance(await store.list_document_workspaces(), list)
    finally:
        await store.close()
