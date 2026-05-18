"""ASOC JWT verification — decode and verify ASOC-issued JWTs (MTRNIX-354, T4).

ASOC issues HMAC-signed JWTs (HS256/HS384/HS512) using a shared secret.  This
module verifies the token and extracts the claims that the chat orchestrator needs.

Algorithm pinning: ``algorithms=[algorithm]`` is always passed to ``jwt.decode``
so the ``none`` algorithm is never accepted, even if the header declares it.

Exception hierarchy (lives here, not in core/exceptions.py — not a MetatronError):
    AsocJwtError
    ├── AsocJwtExpiredError   — ``exp`` has passed
    ├── AsocJwtInvalidError   — bad signature, malformed header, wrong algorithm
    └── AsocJwtMissingClaimError — required claim absent from the verified payload

FastAPI dependency ``asoc_auth`` is a regular async function (not a class).  It
reads ``app.state.settings`` from the request so it works in isolated test apps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)

__all__ = [
    "AsocAuthContext",
    "AsocJwtError",
    "AsocJwtExpiredError",
    "AsocJwtInvalidError",
    "AsocJwtMissingClaimError",
    "asoc_auth",
    "verify_asoc_jwt",
]

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AsocJwtError(Exception):
    """Base for all ASOC JWT verification errors."""


class AsocJwtExpiredError(AsocJwtError):
    """Token ``exp`` has passed."""


class AsocJwtInvalidError(AsocJwtError):
    """Bad signature, malformed header, wrong algorithm, or ``none`` algorithm."""


class AsocJwtMissingClaimError(AsocJwtError):
    """A required claim is absent from the verified payload."""


# ---------------------------------------------------------------------------
# Verified auth context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AsocAuthContext:
    """Verified ASOC JWT context forwarded to the chat orchestrator.

    All fields are extracted from the verified token payload.  ``user_jwt``
    is the raw Bearer token, forwarded verbatim to ASOC MCP / visibility
    filter calls so ASOC can enforce its own per-user permissions.
    """

    user_jwt: str  # raw token, forwarded to ASOC MCP / visibility filter
    user_id: str  # from claim 'user_id' (or 'sub' fallback)
    project_id: str  # from claim 'project_id'
    claims: dict[str, Any]  # full decoded payload (read-only)
    expires_at: datetime  # UTC datetime from claim 'exp'


# ---------------------------------------------------------------------------
# Core verification function
# ---------------------------------------------------------------------------


def verify_asoc_jwt(token: str, secret: str, algorithm: str) -> AsocAuthContext:
    """Decode and verify an ASOC-issued JWT.

    Args:
        token: Raw JWT string (without ``Bearer `` prefix).
        secret: HMAC shared secret.
        algorithm: Must be one of ``HS256``, ``HS384``, ``HS512``.

    Returns:
        :class:`AsocAuthContext` with verified claims.

    Raises:
        AsocJwtExpiredError: ``exp`` claim has passed.
        AsocJwtInvalidError: Bad signature, malformed token, or ``none`` algorithm.
        AsocJwtMissingClaimError: Required claim absent from payload.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],  # algorithm pinning — never accept 'none'
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AsocJwtExpiredError("ASOC JWT has expired") from exc
    except jwt.PyJWTError as exc:
        raise AsocJwtInvalidError(f"ASOC JWT invalid: {exc}") from exc

    # Extract required claims.
    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise AsocJwtMissingClaimError("'user_id' (or 'sub') claim missing")

    project_id = payload.get("project_id")
    if not project_id:
        raise AsocJwtMissingClaimError("'project_id' claim missing")

    # exp is guaranteed by jwt.decode options={"require": ["exp"]} above.
    exp = payload["exp"]
    expires_at = datetime.fromtimestamp(int(exp), tz=UTC)

    logger.debug(
        "asoc_jwt.verified",
        user_id=str(user_id),
        project_id=str(project_id),
    )

    return AsocAuthContext(
        user_jwt=token,
        user_id=str(user_id),
        project_id=str(project_id),
        claims=payload,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def asoc_auth(request: Request) -> AsocAuthContext:
    """FastAPI ``Depends`` that verifies the ASOC Bearer JWT.

    Returns:
        :class:`AsocAuthContext` on success.

    Raises:
        HTTPException 503 if ``asoc_shared_secret`` is not configured.
        HTTPException 401 if the ``Authorization`` header is missing or the
            token is expired / invalid / missing a required claim.
    """
    settings = request.app.state.settings
    if not settings.asoc_shared_secret:
        logger.warning("asoc_auth.secret_not_configured")
        raise HTTPException(status_code=503, detail="asoc_jwt_not_configured")

    auth_header: str = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")

    token = auth_header[len("Bearer ") :].strip()

    try:
        return verify_asoc_jwt(token, settings.asoc_shared_secret, settings.asoc_jwt_algorithm)
    except AsocJwtExpiredError:
        raise HTTPException(status_code=401, detail="token_expired")  # noqa: B904
    except AsocJwtInvalidError:
        raise HTTPException(status_code=401, detail="invalid_token")  # noqa: B904
    except AsocJwtMissingClaimError as exc:
        raise HTTPException(status_code=401, detail=f"missing_claim: {exc}")  # noqa: B904
