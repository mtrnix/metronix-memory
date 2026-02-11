"""FastAPI dependency injection helpers for auth.

Provides Depends() functions for extracting and validating
the current user from JWT bearer tokens in HTTP requests.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from metatron.auth.jwt import verify_token
from metatron.auth.rbac import check_permission
from metatron.core.config import Settings
from metatron.core.exceptions import AuthenticationError
from metatron.core.models import Role, User

logger = structlog.get_logger()

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(),
) -> User:
    """Extract and validate user from JWT bearer token.

    Use as a FastAPI dependency:
        @router.get("/protected")
        async def protected(user: User = Depends(get_current_user)): ...

    Raises:
        HTTPException 401: If token is missing, invalid, or expired.
    """
    try:
        payload = verify_token(credentials.credentials, settings.secret_key)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

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
