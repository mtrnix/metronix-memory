"""Persistence coverage for temporary conversation events and session ledgers."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.memory.conversation_models import ConversationEvent, SessionLedger
from metronix.storage.conversation_postgres import ConversationPostgresStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def store() -> ConversationPostgresStore:
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    yield ConversationPostgresStore(engine)
    await engine.dispose()


async def test_expiring_events_retains_ledger_provenance(store: ConversationPostgresStore) -> None:
    workspace_id = f"conversation-ws-{uuid4().hex}"
    agent_id = f"agent-{uuid4().hex}"
    session_id = f"session-{uuid4().hex}"
    event = ConversationEvent.new(workspace_id, agent_id, session_id, "user", "hello")

    await store.append_event(event)
    assert await store.list_uncompacted(workspace_id, agent_id, session_id) == [event]

    ledger = SessionLedger.new(event, source_hashes=[event.content_hash])
    await store.save_ledger(ledger)
    assert await store.expire_events(older_than=datetime.now(UTC) + timedelta(seconds=1)) == 1

    stored_ledger = await store.get_ledger(workspace_id, agent_id, session_id)
    assert stored_ledger is not None
    assert stored_ledger.source_hashes == [event.content_hash]
