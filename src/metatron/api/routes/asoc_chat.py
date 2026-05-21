"""ASOC pilot chat REST endpoints (MTRNIX-353 T3 + MTRNIX-354 T4).

# NOTE: ASOC pilot endpoint. The "no /api/v1/chat/* endpoints" rule in CLAUDE.md
# targets built-in chat UIs; this is a backend for an external (ASOC) UI.
# Exception documented in MTRNIX-358 (T8 docs).

Router is mounted at /api/v1/asoc (T4 renames from /api/v1 in app.py).
Final endpoint URLs:
- POST   /api/v1/asoc/chat          — streaming chat (T4, ASOC JWT auth)
- GET    /api/v1/asoc/chat/threads  — list threads (ASOC JWT auth)
- GET    /api/v1/asoc/chat/threads/{id}/messages
- DELETE /api/v1/asoc/chat/threads/{id}
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from metatron.api.dependencies import get_chat_persistence
from metatron.auth.asoc_jwt import AsocAuthContext, asoc_auth
from metatron.chat.models import ChatMessage, ChatThread  # noqa: TC001 — used in from_domain
from metatron.chat.persistence import ChatPersistence  # noqa: TC001 — FastAPI Depends runtime

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["asoc-chat"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AsocChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8192)
    history: list[dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ChatThreadResponse(BaseModel):
    thread_id: str
    workspace_id: str
    user_id: str
    created_at: str
    last_message_at: str | None

    @classmethod
    def from_domain(cls, thread: ChatThread) -> ChatThreadResponse:
        return cls(
            thread_id=str(thread.thread_id),
            workspace_id=thread.workspace_id,
            user_id=thread.user_id,
            created_at=thread.created_at.isoformat(),
            last_message_at=(
                thread.last_message_at.isoformat() if thread.last_message_at else None
            ),
        )


class ChatThreadListResponse(BaseModel):
    threads: list[ChatThreadResponse]
    count: int


class ChatMessageResponse(BaseModel):
    id: str
    thread_id: str
    role: str
    content: str
    citations_json: list[dict[str, Any]] | None
    tool_calls_json: list[dict[str, Any]] | None
    created_at: str

    @classmethod
    def from_domain(cls, msg: ChatMessage) -> ChatMessageResponse:
        return cls(
            id=str(msg.id),
            thread_id=str(msg.thread_id),
            role=str(msg.role),
            content=msg.content,
            citations_json=msg.citations_json,
            tool_calls_json=msg.tool_calls_json,
            created_at=msg.created_at.isoformat(),
        )


class ChatMessageListResponse(BaseModel):
    messages: list[ChatMessageResponse]
    count: int


# ---------------------------------------------------------------------------
# DI helper
# ---------------------------------------------------------------------------


def get_asoc_chat_orchestrator(request: Request):  # type: ignore[no-untyped-def]
    """Return the :class:`AsocChatOrchestrator` from app state.

    Raises 503 if the orchestrator was not initialised (missing config or deps).
    """
    orch = getattr(request.app.state, "asoc_chat_orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="asoc_chat_not_configured")
    return orch


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/chat")
async def asoc_chat(
    body: AsocChatRequest,
    request: Request,
    auth: Annotated[AsocAuthContext, Depends(asoc_auth)],
    orchestrator: Annotated[Any, Depends(get_asoc_chat_orchestrator)],
) -> EventSourceResponse:
    """ASOC streaming chat endpoint.

    Accepts ASOC-issued JWT in ``Authorization: Bearer <token>`` header.
    Streams SSE events: ``status``, ``chunk``, ``sources``, ``tool_call``,
    ``done``, ``error``.

    The ``done`` event is always last, even on error.

    Rate-limit check runs BEFORE opening the SSE stream so ASOC analytics
    receives a clean HTTP 429 (not a 200 + SSE error event).
    """
    # Rate-limit check — must happen before EventSourceResponse is returned so
    # the client gets HTTP 429, not a 200 OK followed by an SSE error event.
    rate_limiter = getattr(request.app.state, "asoc_rate_limiter", None)
    if rate_limiter is not None:
        allowed = await rate_limiter.acquire(auth.user_id)
        if not allowed:
            raise HTTPException(status_code=429, detail="rate_limited")

    return EventSourceResponse(orchestrator.run(auth, body, request))


@router.get("/chat/threads", response_model=ChatThreadListResponse)
async def list_chat_threads(
    request: Request,
    persistence: Annotated[ChatPersistence, Depends(get_chat_persistence)],
    auth: Annotated[AsocAuthContext, Depends(asoc_auth)],
    # DEPRECATED query params — kept for backward compat, will be removed in phase 2.
    # T4 derives workspace and user from the ASOC JWT directly.
    workspace_id: Annotated[
        str | None,
        Query(
            description="[DEPRECATED] Ignored — workspace derived from JWT project_id.",
            include_in_schema=False,
        ),
    ] = None,
    user_id: Annotated[
        str | None,
        Query(
            description="[DEPRECATED] Ignored — user derived from JWT user_id.",
            include_in_schema=False,
        ),
    ] = None,
) -> ChatThreadListResponse:
    """List chat threads for the authenticated ASOC user.

    Workspace and user are derived from the ASOC JWT.  The legacy
    ``workspace_id`` / ``user_id`` query params are ignored (will be removed
    in phase 2).
    """
    settings = request.app.state.settings
    instance = settings.asoc_instance_id or "default"
    effective_workspace_id = f"asoc-{instance}-{auth.project_id}"
    threads = await persistence.list_threads(effective_workspace_id, auth.user_id)
    return ChatThreadListResponse(
        threads=[ChatThreadResponse.from_domain(t) for t in threads],
        count=len(threads),
    )


@router.get(
    "/chat/threads/{thread_id}/messages",
    response_model=ChatMessageListResponse,
)
async def list_thread_messages(
    thread_id: str,
    request: Request,
    persistence: Annotated[ChatPersistence, Depends(get_chat_persistence)],
    auth: Annotated[AsocAuthContext, Depends(asoc_auth)],
    limit: Annotated[int | None, Query(ge=1, le=1000, description="Max messages")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatMessageListResponse:
    """Return messages for a thread, oldest first.

    Workspace is derived from the ASOC JWT.  Returns 404 if the thread does
    not exist in the user's workspace.  Returns 400 if ``thread_id`` is not
    a valid UUID.
    """
    try:
        tid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="thread_id must be a valid UUID")  # noqa: B904

    settings = request.app.state.settings
    instance = settings.asoc_instance_id or "default"
    workspace = f"asoc-{instance}-{auth.project_id}"

    thread = await persistence.get_thread(workspace, tid)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    messages = await persistence.list_messages(workspace, tid, limit=limit, offset=offset)
    return ChatMessageListResponse(
        messages=[ChatMessageResponse.from_domain(m) for m in messages],
        count=len(messages),
    )


@router.delete("/chat/threads/{thread_id}", status_code=204)
async def delete_chat_thread(
    thread_id: str,
    request: Request,
    persistence: Annotated[ChatPersistence, Depends(get_chat_persistence)],
    auth: Annotated[AsocAuthContext, Depends(asoc_auth)],
) -> None:
    """Delete a thread and all its messages (CASCADE).

    Workspace is derived from the ASOC JWT.  Returns 204 on success, 404 if
    the thread does not exist in this workspace.  Returns 400 for invalid UUID.
    """
    try:
        tid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="thread_id must be a valid UUID")  # noqa: B904

    settings = request.app.state.settings
    instance = settings.asoc_instance_id or "default"
    workspace = f"asoc-{instance}-{auth.project_id}"

    deleted = await persistence.delete_thread(workspace, tid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
