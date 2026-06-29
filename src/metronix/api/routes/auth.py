"""Auth API — login and session endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from metronix.auth.jwt import create_token
from metronix.auth.passwords import verify_password
from metronix.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str | None = None
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    email: str = ""
    display_name: str = ""
    role: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate with email+password or legacy shared password."""
    settings = get_settings()

    # New flow: email + password → DB lookup
    if req.email:
        user_store = getattr(request.app.state, "user_store", None)
        if not user_store:
            raise HTTPException(status_code=500, detail="User store not available")

        user = await user_store.get_user_by_email(req.email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Account is disabled")

        if not verify_password(req.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        workspace_ids = user.get("workspace_ids", []) or []
        # Admin role with no per-workspace confinement means "all workspaces".
        # Issuing `[]` would later 403 under the strict workspace resolver, so
        # normalise here at token-issue time (mirrored in OptionalAuthMiddleware
        # for older tokens already in circulation).
        if user["role"] == "admin" and not workspace_ids:
            workspace_ids = ["*"]
        token = create_token(
            user_id=user["id"],
            role=user["role"],
            workspace_ids=workspace_ids,
            secret_key=settings.secret_key,
            expiry_hours=24,
            email=user["email"],
        )
        logger.info("auth.login.success", user_id=user["id"], email=user["email"])
        return LoginResponse(
            token=token,
            user_id=user["id"],
            email=user["email"],
            display_name=user.get("display_name", ""),
            role=user["role"],
        )

    # Legacy fallback: password only (no email)
    logger.warning("auth.login.legacy_fallback", hint="Use email+password instead")
    if req.password != settings.auth_password:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(
        user_id="admin",
        role="admin",
        workspace_ids=["*"],
        secret_key=settings.secret_key,
        expiry_hours=24,
    )
    return LoginResponse(token=token, user_id="admin", role="admin")


@router.get("/auth/me")
def me(request: Request) -> dict:
    """Return current user info from JWT."""
    user = getattr(request.state, "user", {})
    return {
        "status": "ok",
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "role": user.get("role", ""),
    }
