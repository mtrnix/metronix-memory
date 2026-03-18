"""User management API — admin only."""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

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
    workspace_ids: list[str] = []


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class AddWorkspaceRequest(BaseModel):
    workspace_id: str


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
            workspace_ids=req.workspace_ids,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email already exists")
        raise
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


@router.get("/users/{user_id}")
async def get_user(user_id: str, request: Request) -> dict:
    _require_admin(request)
    user_store = _get_user_store(request)
    user = await user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


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
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request) -> None:
    caller = _require_admin(request)
    if caller.get("user_id") == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user_store = _get_user_store(request)
    if not await user_store.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")


@router.post("/users/{user_id}/workspaces", status_code=201)
async def add_workspace(user_id: str, req: AddWorkspaceRequest, request: Request) -> dict:
    _require_admin(request)
    user_store = _get_user_store(request)
    user = await user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user_store.add_workspace(user_id, req.workspace_id)
    return {"user_id": user_id, "workspace_id": req.workspace_id}


@router.delete("/users/{user_id}/workspaces/{workspace_id}", status_code=204)
async def remove_workspace(user_id: str, workspace_id: str, request: Request) -> None:
    _require_admin(request)
    user_store = _get_user_store(request)
    await user_store.remove_workspace(user_id, workspace_id)
