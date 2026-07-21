"""Authenticated controls for compaction of agent-owned conversation sessions."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel

from metronix.activity.context import current_agent_id
from metronix.agents.service import AgentNotFoundError, AgentRegistryService
from metronix.api.dependencies import (
    get_agent_registry_service,
    get_memory_service,
    resolve_workspace_id,
    workspace_scope,
)
from metronix.auth.dependencies import require_editor
from metronix.core.models import User
from metronix.memory.compaction import CompactionController
from metronix.memory.service import MemoryService
from metronix.storage.conversation_postgres import ConversationPostgresStore

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(workspace_scope)],
)


class CompactionResponse(BaseModel):
    ledger_id: str | None
    generation: int | None
    source_event_count: int
    memory_record_count: int
    rejected_candidate_count: int


def get_conversation_store(request: Request) -> ConversationPostgresStore:
    """Return the shared event store, constructing it on demand for REST use."""
    store = getattr(request.app.state, "conversation_store", None)
    if store is not None:
        return cast(ConversationPostgresStore, store)

    from sqlalchemy.ext.asyncio import create_async_engine

    settings = request.app.state.settings
    engine = getattr(request.app.state, "memory_pg_engine", None)
    if engine is None:
        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        request.app.state.memory_pg_engine = engine
    store = ConversationPostgresStore(
        engine,
        retention_policy=settings.conversation_event_retention,
    )
    request.app.state.conversation_store = store
    return store


@router.post("/{session_id}/compact", response_model=CompactionResponse)
async def compact_conversation(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"),
    ],
    request: Request,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    agent_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> CompactionResponse:
    """Explicitly compact one authenticated workspace/agent session."""
    agent_id = current_agent_id.get()
    if agent_id is None:
        raise HTTPException(status_code=400, detail="x_agent_id_required")
    workspace_id = resolve_workspace_id(request)
    try:
        await agent_service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    controller = CompactionController(
        get_conversation_store(request),
        memory_service,
        settings=request.app.state.settings,
    )
    result = await controller.compact(workspace_id, agent_id, session_id, reason="explicit_api")
    ledger = result.ledger
    source_event_count = 0
    if ledger is not None:
        source_value = ledger.summary.get("source_event_count")
        if isinstance(source_value, int) and not isinstance(source_value, bool):
            source_event_count = source_value
    return CompactionResponse(
        ledger_id=None if ledger is None else ledger.id,
        generation=None if ledger is None else ledger.generation,
        source_event_count=source_event_count,
        memory_record_count=len(result.memory_records),
        rejected_candidate_count=result.rejected_count,
    )
