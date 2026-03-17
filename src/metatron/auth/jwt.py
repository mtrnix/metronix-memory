"""JWT token creation and verification using PyJWT.

Tokens are HS256-signed using the app's secret key.
Payload includes: user_id, role, workspace_ids, exp.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import structlog

from metatron.core.exceptions import AuthenticationError

logger = structlog.get_logger()

ALGORITHM = "HS256"
DEFAULT_EXPIRY_HOURS = 24


def create_token(
    user_id: str,
    role: str,
    workspace_ids: list[str],
    secret_key: str,
    expiry_hours: int = DEFAULT_EXPIRY_HOURS,
    email: str = "",
) -> str:
    """Create a signed JWT token.

    Args:
        user_id: Internal user ID.
        role: User role (admin, editor, viewer).
        workspace_ids: List of workspace IDs the user can access.
        secret_key: HMAC signing key.
        expiry_hours: Token lifetime in hours.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "workspace_ids": workspace_ids,
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
    }
    if email:
        payload["email"] = email
    token = jwt.encode(payload, secret_key, algorithm=ALGORITHM)
    logger.info("auth.jwt.created", user_id=user_id, expiry_hours=expiry_hours)
    return token


def verify_token(token: str, secret_key: str) -> dict[str, object]:
    """Verify and decode a JWT token.

    Args:
        token: Encoded JWT string.
        secret_key: HMAC signing key (must match creation key).

    Returns:
        Decoded payload dict with sub, role, workspace_ids.

    Raises:
        AuthenticationError: If token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        logger.info("auth.jwt.verified", user_id=payload.get("sub"))
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {e}")
