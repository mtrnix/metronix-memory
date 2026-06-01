"""Activity correlation_id column + filter (MTRNIX-372 P3)."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import Settings
from metatron.storage.activity_pg import ActivityRow, ActivityStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def store():
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    yield ActivityStore(engine)
    await engine.dispose()


async def test_insert_and_filter_by_correlation(store: ActivityStore) -> None:
    await store.insert(
        ActivityRow(
            workspace_id="WS_C", agent_id="AG_C", event_type="proxy.request.received",
            event_data={}, correlation_id="corr-xyz",
        )
    )
    await store.insert(
        ActivityRow(
            workspace_id="WS_C", agent_id="AG_C", event_type="proxy.upstream.completed",
            event_data={}, correlation_id="corr-xyz",
        )
    )
    await store.insert(
        ActivityRow(
            workspace_id="WS_C", agent_id="AG_C", event_type="other",
            event_data={}, correlation_id="corr-other",
        )
    )
    rows = await store.list_for_agent(
        workspace_id="WS_C", agent_id="AG_C", since=None, until=None,
        event_types=None, session_id=None, correlation_id="corr-xyz",
        limit=50, offset=0,
    )
    assert len(rows) == 2
    assert {r["event_type"] for r in rows} == {
        "proxy.request.received", "proxy.upstream.completed"
    }
    assert all(r["correlation_id"] == "corr-xyz" for r in rows)
