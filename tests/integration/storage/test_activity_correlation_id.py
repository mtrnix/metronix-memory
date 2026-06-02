"""Activity correlation_id column + filter (MTRNIX-372 P3)."""

from uuid import uuid4

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
    # agent_activity_log is append-only with no cleanup; use unique ids per run
    # so repeated runs stay idempotent.
    corr = uuid4().hex
    other = uuid4().hex
    agent = f"AG_{uuid4().hex[:8]}"
    await store.insert(
        ActivityRow(
            workspace_id="WS_C", agent_id=agent, event_type="proxy.request.received",
            event_data={}, correlation_id=corr,
        )
    )
    await store.insert(
        ActivityRow(
            workspace_id="WS_C", agent_id=agent, event_type="proxy.upstream.completed",
            event_data={}, correlation_id=corr,
        )
    )
    await store.insert(
        ActivityRow(
            workspace_id="WS_C", agent_id=agent, event_type="other",
            event_data={}, correlation_id=other,
        )
    )
    rows = await store.list_for_agent(
        workspace_id="WS_C", agent_id=agent, since=None, until=None,
        event_types=None, session_id=None, correlation_id=corr,
        limit=50, offset=0,
    )
    assert len(rows) == 2
    assert {r["event_type"] for r in rows} == {
        "proxy.request.received", "proxy.upstream.completed"
    }
    assert all(r["correlation_id"] == corr for r in rows)
