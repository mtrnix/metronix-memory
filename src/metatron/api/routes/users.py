"""User management API — admin only."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from metatron.api.dependencies import get_chat_persistence
from metatron.auth.asoc_session import asoc_admin_auth
from metatron.auth.passwords import validate_password

logger = structlog.get_logger()

router = APIRouter(tags=["users"])


def _require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _get_user_store(request: Request):
    store = getattr(request.app.state, "user_store", None)
    if not store:
        raise HTTPException(status_code=503, detail="User store not available")
    return store


class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    email: str | None = None
    password: str | None = None
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


@router.post("/users", status_code=201)
async def create_user(req: CreateUserRequest, request: Request) -> dict:
    _require_admin(request)
    validate_password(req.password)
    user_store = _get_user_store(request)
    try:
        user = await user_store.create_user(
            email=req.email,
            password=req.password,
            display_name=req.display_name,
            role=req.role,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email already exists")
        raise

    # Generate API key and sync to Open WebUI
    api_key_store = getattr(request.app.state, "api_key_store", None)
    if api_key_store:
        raw_key = await api_key_store.create_key(user_id=user["id"], label="default")
        user["api_key"] = raw_key

        owui_sync = getattr(request.app.state, "owui_sync", None)
        if owui_sync and owui_sync.enabled:
            sync_result = await owui_sync.sync_user_created(
                email=req.email,
                name=req.display_name or req.email,
                password=req.password,
                role=req.role,
                api_key=raw_key,
            )
            if sync_result:
                user["owui_synced"] = True
                await user_store.update_user(
                    user["id"],
                    owui_user_id=sync_result["owui_user_id"],
                )

    return user


@router.get("/users")
async def list_users(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    _require_admin(request)
    user_store = _get_user_store(request)
    users, total = await user_store.list_users(limit=limit, offset=offset)
    return {"users": users, "total": total}


def _sanitize_user(user: dict) -> dict:
    """Remove internal fields from user dict before returning to API."""
    return {k: v for k, v in user.items() if k not in ("owui_user_id",)}


@router.get("/users/{user_id}")
async def get_user(user_id: str, request: Request) -> dict:
    _require_admin(request)
    user_store = _get_user_store(request)
    user = await user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _sanitize_user(user)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, request: Request) -> dict:
    caller = _require_admin(request)
    user_store = _get_user_store(request)

    updates = req.model_dump(exclude_none=True)

    # Lockout protection
    if caller.get("user_id") == user_id and "role" in updates:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    if "password" in updates:
        validate_password(updates["password"])

    user = await user_store.update_user(user_id, **updates)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Sync update to Open WebUI
    owui_sync = getattr(request.app.state, "owui_sync", None)
    owui_id = user.get("owui_user_id")
    if owui_sync and owui_sync.enabled and owui_id:
        await owui_sync.sync_user_updated(
            owui_user_id=owui_id,
            name=user.get("display_name", ""),
            email=user.get("email", ""),
            role=user.get("role", "viewer"),
            password=updates.get("password"),
        )

    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request) -> None:
    caller = _require_admin(request)
    if caller.get("user_id") == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user_store = _get_user_store(request)

    # Get owui_user_id before deleting
    user = await user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not await user_store.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")

    # Sync delete to Open WebUI
    owui_sync = getattr(request.app.state, "owui_sync", None)
    owui_id = user.get("owui_user_id")
    if owui_sync and owui_sync.enabled and owui_id:
        await owui_sync.sync_user_deleted(owui_user_id=owui_id)

    # Workspace management removed — workspace access is managed through
    # enterprise access groups. Adding a user to a group automatically
    # grants workspace access. Removing from all groups in a workspace
    # revokes access.


# --- ASOC user-cascade: delete all chat threads for a user (MTRNIX-353, T3) ---


@router.delete("/users/{user_id}/chats", status_code=204)
async def delete_user_chats(
    user_id: str,
    request: Request,
    _admin: Annotated[None, Depends(asoc_admin_auth)],
    persistence: Annotated[object, Depends(get_chat_persistence)],
) -> None:
    """Delete all chat threads (and cascade messages) for a user across all workspaces.

    ASOC-admin-only.  Idempotent — returns 204 even when the user has no threads.
    Called by ASOC when a user is deleted on their side to ensure no orphaned
    chat history remains in Metatron.
    """
    await persistence.delete_threads_for_user(user_id)


# --- Personal API keys for /v1 endpoints ---


def _get_api_key_store(request: Request):
    store = getattr(request.app.state, "api_key_store", None)
    if not store:
        raise HTTPException(status_code=503, detail="API key store not available")
    return store


@router.post("/users/{user_id}/api-keys", status_code=201)
async def create_api_key(user_id: str, request: Request) -> dict:
    _require_admin(request)
    api_store = _get_api_key_store(request)
    user_store = _get_user_store(request)
    if not await user_store.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    raw_key = await api_store.create_key(user_id=user_id, label="default")
    return {"raw_key": raw_key, "user_id": user_id}


@router.get("/users/{user_id}/api-keys")
async def list_api_keys(user_id: str, request: Request) -> dict:
    _require_admin(request)
    api_store = _get_api_key_store(request)
    keys = await api_store.list_keys(user_id=user_id)
    return {"keys": keys, "user_id": user_id}


@router.delete("/users/{user_id}/api-keys/{key_prefix}", status_code=204)
async def revoke_api_key(user_id: str, key_prefix: str, request: Request) -> None:
    _require_admin(request)
    api_store = _get_api_key_store(request)
    if not await api_store.revoke_key(key_prefix=key_prefix, user_id=user_id):
        raise HTTPException(status_code=404, detail="Key not found")


# --- Platform user mappings (admin CRUD) ---


def _get_mapper(request: Request):
    mapper = getattr(request.app.state, "platform_mapper", None)
    if not mapper:
        raise HTTPException(
            status_code=503,
            detail="Platform mapper not available",
        )
    return mapper


def _get_workspace_id(request: Request, workspace_id: str | None) -> str:
    if workspace_id and workspace_id != "*":
        return workspace_id
    user = getattr(request.state, "user", {}) or {}
    ws_ids = user.get("workspace_ids", [])
    if ws_ids and ws_ids[0] != "*":
        return ws_ids[0]
    settings = request.app.state.settings
    return settings.default_workspace_id


class UpdateMappingRequest(BaseModel):
    user_id: str


@router.get("/users/platform-mappings")
async def list_platform_mappings(
    request: Request,
    channel: str | None = Query(None),
    workspace_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    _require_admin(request)
    mapper = _get_mapper(request)
    ws = _get_workspace_id(request, workspace_id)
    mappings = await mapper.list_mappings(
        workspace_id=ws,
        channel=channel,
        limit=limit,
        offset=offset,
    )
    return {"mappings": mappings, "workspace_id": ws}


@router.get("/users/{user_id}/platform-mappings")
async def get_user_platform_mappings(
    user_id: str,
    request: Request,
    workspace_id: str | None = Query(None),
) -> dict:
    _require_admin(request)
    mapper = _get_mapper(request)
    ws = _get_workspace_id(request, workspace_id)
    mappings = await mapper.get_mappings_for_user(
        user_id=user_id,
        workspace_id=ws,
    )
    return {"mappings": mappings, "user_id": user_id}


@router.put(
    "/users/platform-mappings/{channel}/{channel_user_id}",
)
async def update_platform_mapping(
    channel: str,
    channel_user_id: str,
    req: UpdateMappingRequest,
    request: Request,
    workspace_id: str | None = Query(None),
) -> dict:
    _require_admin(request)
    mapper = _get_mapper(request)
    ws = _get_workspace_id(request, workspace_id)
    updated = await mapper.update_mapping(
        channel=channel,
        channel_user_id=channel_user_id,
        workspace_id=ws,
        new_user_id=req.user_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"status": "updated"}


@router.delete(
    "/users/platform-mappings/{channel}/{channel_user_id}",
    status_code=204,
)
async def delete_platform_mapping(
    channel: str,
    channel_user_id: str,
    request: Request,
    workspace_id: str | None = Query(None),
) -> None:
    _require_admin(request)
    mapper = _get_mapper(request)
    ws = _get_workspace_id(request, workspace_id)
    deleted = await mapper.delete_mapping(
        channel=channel,
        channel_user_id=channel_user_id,
        workspace_id=ws,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping not found")
