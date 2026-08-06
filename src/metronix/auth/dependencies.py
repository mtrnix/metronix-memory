"""FastAPI dependency injection helpers for auth.

Provides Depends() functions for extracting and validating
the current user from JWT bearer tokens in HTTP requests.

Auth resolution order:
1. If a plugin has registered an AuthBackendInterface via PluginManager,
   delegate to provider.authenticate(token).
2. Otherwise, fall back to the built-in JWT verification (jwt.py).

This allows enterprise to swap in SAML/OIDC without touching core code.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from metronix.auth.jwt import verify_token
from metronix.auth.rbac import check_permission
from metronix.core.config import Settings
from metronix.core.exceptions import AuthenticationError
from metronix.core.models import Role, User

logger = structlog.get_logger()

_bearer_scheme = HTTPBearer()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_claims(payload: dict[str, object]) -> User:
    """Build a user from claims while preserving legacy admin semantics."""
    role = Role(str(payload.get("role", "viewer")))
    workspace_ids = list(payload.get("workspace_ids", []) or [])
    if role == Role.ADMIN and not workspace_ids:
        workspace_ids = ["*"]
    return User(
        id=str(payload["sub"]),
        email=str(payload.get("email", "")),
        role=role,
        workspace_ids=workspace_ids,
    )


async def authenticate_request_token(request: Request, token: str) -> User:
    """Resolve plugin credentials, JWTs, or personal API keys into a user."""
    return await _authenticate_request_token(request, token)


async def _authenticate_request_token(request: Request, token: str) -> User:
    """Extract and validate user from the bearer token.

    Checks for a plugin-registered auth provider first; falls back to
    the built-in JWT verification if none is registered.

    Use as a FastAPI dependency:
        @router.get("/protected")
        async def protected(user: User = Depends(get_current_user)): ...

    Raises:
        HTTPException 401: If token is missing, invalid, or expired.
    """
    # --- Plugin auth provider (e.g. SAML, OIDC) ---
    plugin_manager = getattr(request.app.state, "plugin_manager", None)
    if plugin_manager is not None:
        provider = plugin_manager.get_auth_provider()
        if provider is not None:
            try:
                user = await provider.authenticate(token)
            except Exception as exc:
                logger.warning("auth.plugin_provider.failed", error=str(exc))
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication failed",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user

    settings: Settings = request.app.state.settings
    try:
        payload = verify_token(token, settings.secret_key)
        return _user_from_claims(payload)
    except (AuthenticationError, KeyError, TypeError, ValueError):
        pass

    api_key_store = getattr(request.app.state, "api_key_store", None)
    user_store = getattr(request.app.state, "user_store", None)
    if api_key_store is None or user_store is None:
        raise _unauthorized("Invalid or expired token")

    resolved = await api_key_store.resolve_key(token)
    if resolved is None or resolved.get("source") != "personal":
        raise _unauthorized("Invalid or expired token")

    owner = await user_store.get_user_by_id(str(resolved["user_id"]))
    if owner is None or not owner.get("is_active", False):
        raise _unauthorized("Invalid or expired token")

    try:
        return _user_from_claims(
            {
                "sub": owner["id"],
                "email": owner.get("email", ""),
                "role": owner["role"],
                "workspace_ids": owner.get("workspace_ids", []),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("auth.personal_key.owner_invalid", error=str(exc))
        raise _unauthorized("Invalid or expired token") from exc


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> User:
    """Extract and validate the current user from a bearer credential."""
    return await authenticate_request_token(request, credentials.credentials)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires admin role.

    Raises:
        HTTPException 403: If user is not an admin.
    """
    if not check_permission(user.role, Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_editor(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires editor role or higher."""
    if not check_permission(user.role, Role.EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editor access required",
        )
    return user


def require_viewer(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires viewer role or higher."""
    if not check_permission(user.role, Role.VIEWER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Viewer access required",
        )
    return user
