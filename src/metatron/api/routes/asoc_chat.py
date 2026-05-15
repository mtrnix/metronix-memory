"""ASOC pilot chat-history REST endpoints (MTRNIX-353, T3).

# NOTE: ASOC pilot endpoint. The "no /api/v1/chat/* endpoints" rule in CLAUDE.md
# targets built-in chat UIs; this is a backend for an external (ASOC) UI.
# Exception documented in MTRNIX-358 (T8 docs).

Three skeleton endpoints shipped in T3:
- GET  /api/v1/chat/threads           — list threads for (workspace, user)
- GET  /api/v1/chat/threads/{id}/messages — list messages in a thread
- DELETE /api/v1/chat/threads/{id}    — delete a thread + cascade messages

Auth is the existing require_viewer / require_editor gate.
TODO(MTRNIX-354): replace with ASOC-issued JWT middleware once T4 lands.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from metatron.api.dependencies import get_chat_persistence, get_workspace_id
from metatron.auth.dependencies import require_editor, require_viewer
from metatron.chat.models import ChatMessage, ChatThread  # noqa: TC001 — used in from_domain
from metatron.chat.persistence import ChatPersistence  # noqa: TC001 — FastAPI Depends runtime
from metatron.core.models import User  # noqa: TC001 — FastAPI Depends return type

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["asoc-chat"])


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
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/chat/threads", response_model=ChatThreadListResponse)
async def list_chat_threads(
    request: Request,
    workspace_id: Annotated[str, Query(description="Workspace to scope the thread listing")],
    user_id: Annotated[str, Query(description="User whose threads to list")],
    persistence: Annotated[ChatPersistence, Depends(get_chat_persistence)],
    _viewer: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
) -> ChatThreadListResponse:
    """List chat threads for a (workspace, user) pair.

    The caller's authenticated workspace must match ``workspace_id``.
    TODO(MTRNIX-354): replace workspace check with ASOC-JWT claim validation.
    """
    auth_workspace = get_workspace_id(request)
    # If the authenticated workspace is a wildcard ("*") we allow any value —
    # that is the admin-token case.  Otherwise enforce strict equality.
    if auth_workspace != "*" and auth_workspace != workspace_id:
        raise HTTPException(
            status_code=403,
            detail="Workspace mismatch: caller is not authorised for the requested workspace.",
        )
    threads = await persistence.list_threads(workspace_id, user_id)
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
    _viewer: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    limit: Annotated[int | None, Query(ge=1, le=1000, description="Max messages")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatMessageListResponse:
    """Return messages for a thread, oldest first.

    Returns 404 if the thread does not exist in the caller's workspace.
    Returns 400 if ``thread_id`` is not a valid UUID.
    """
    try:
        tid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="thread_id must be a valid UUID")  # noqa: B904

    workspace = get_workspace_id(request)
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
    _editor: Annotated[User, Depends(require_editor)],  # noqa: ARG001
) -> None:
    """Delete a thread and all its messages (CASCADE).

    Returns 204 on success, 404 if the thread does not exist in this workspace.
    Returns 400 if ``thread_id`` is not a valid UUID.
    """
    try:
        tid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="thread_id must be a valid UUID")  # noqa: B904

    workspace = get_workspace_id(request)
    deleted = await persistence.delete_thread(workspace, tid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
