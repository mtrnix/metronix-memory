"""Conversation compaction route and prompt-injection integration coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from metronix.agents.models import AgentRecord
from metronix.api.app import create_app
from metronix.api.dependencies import get_agent_registry_service, get_memory_service
from metronix.auth.dependencies import get_current_user
from metronix.core.config import Settings
from metronix.core.models import Role, User
from metronix.memory.assembler import AgentContextAssembler
from metronix.memory.conversation_models import ConversationEvent
from metronix.storage.conversation_postgres import ConversationPostgresStore

pytestmark = pytest.mark.integration


def _user() -> User:
    return User(id="editor-1", role=Role.EDITOR, workspace_ids=["ws-conversation"])


async def test_compacted_ledger_is_injected_without_raw_event_text() -> None:
    """An editor can compact its agent session, but raw event text never enters a prompt."""
    settings = Settings(
        DEFAULT_WORKSPACE_ID="ws-conversation",
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5433,
    )
    app = create_app(settings)

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.postgres_dsn)
    events = ConversationPostgresStore(engine, retention_policy="7d")
    app.state.conversation_store = events

    memory_service = MagicMock()
    memory_service.list_preferences = AsyncMock(return_value=[])
    registry = MagicMock()
    registry.get_agent = AsyncMock(
        return_value=AgentRecord(
            id="agent-a",
            workspace_id="ws-conversation",
            name="Conversation agent",
            model="test",
        )
    )
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_memory_service] = lambda: memory_service
    app.dependency_overrides[get_agent_registry_service] = lambda: registry

    session_id = f"s-{uuid4().hex}"
    raw_event_text = "temporary verbose text"
    await events.append_event(
        ConversationEvent.new("ws-conversation", "agent-a", session_id, "user", raw_event_text)
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/conversations/{session_id}/compact",
            headers={"X-Agent-Id": "agent-a"},
        )
    assert response.status_code == 200
    assert response.json()["source_event_count"] == 1

    assembler = AgentContextAssembler(
        memory_service,
        None,
        settings,
        conversation_events=events,
    )
    context = await assembler.assemble(
        "agent-a",
        "ws-conversation",
        "What do I prefer?",
        session_id=session_id,
    )

    assert "<session_ledger>" in context.system_prompt
    assert raw_event_text not in context.system_prompt

    await engine.dispose()
