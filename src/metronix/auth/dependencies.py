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


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> User:
    """Extract and validate user from the bearer token.

    Checks for a plugin-registered auth provider first; falls back to
    the built-in JWT verification if none is registered.

    Use as a FastAPI dependency:
        @router.get("/protected")
        async def protected(user: User = Depends(get_current_user)): ...

    Raises:
        HTTPException 401: If token is missing, invalid, or expired.
    """
    token = credentials.credentials

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

    # --- Default: built-in JWT ---
    settings: Settings = request.app.state.settings
    try:
        payload = verify_token(token, settings.secret_key)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    return User(
        id=str(payload["sub"]),
        role=Role(str(payload.get("role", "viewer"))),
        workspace_ids=list(payload.get("workspace_ids", [])),
    )


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
