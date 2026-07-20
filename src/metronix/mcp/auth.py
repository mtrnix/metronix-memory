"""MCP HTTP authentication middleware.

Provides API key validation for HTTP transport.
"""

from __future__ import annotations

import hmac
import os

import structlog

from metronix.auth.jwt import verify_token
from metronix.core.exceptions import AuthenticationError
from metronix.mcp.principal import MCPPrincipal

logger = structlog.get_logger()


def get_api_key() -> str | None:
    """Get the configured API key from environment.

    Returns:
        API key string if configured, None otherwise.
    """
    return os.environ.get("METRONIX_MCP_API_KEY")


def validate_api_key(authorization_header: str | None) -> bool:
    """Validate the authorization header for MCP HTTP requests.

    Args:
        authorization_header: The Authorization header value (e.g., "Bearer <key>")

    Returns:
        True if the request is authorized, False otherwise.
    """
    # Get configured API key
    configured_key = get_api_key()

    # If no API key is configured, allow all requests (dev mode)
    if not configured_key:
        logger.debug("mcp.auth.no_api_key_configured", mode="development")
        return True

    # If no authorization header provided, reject
    if not authorization_header:
        logger.warning("mcp.auth.missing_authorization_header")
        return False

    # Check for Bearer token format
    if not authorization_header.startswith("Bearer "):
        logger.warning("mcp.auth.invalid_authorization_format")
        return False

    # Extract the token
    token = authorization_header[7:]  # Remove "Bearer " prefix

    # Validate token (timing-safe comparison)
    if not hmac.compare_digest(token, configured_key):
        logger.warning("mcp.auth.invalid_api_key")
        return False

    logger.debug("mcp.auth.success")
    return True


def require_api_key(authorization_header: str | None) -> None:
    """Require a valid API key, raising an exception if invalid.

    Args:
        authorization_header: The Authorization header value

    Raises:
        PermissionError: If the API key is invalid
    """
    if not validate_api_key(authorization_header):
        raise PermissionError("Invalid or missing API key")


def authenticate_jwt(authorization_header: str | None, secret_key: str) -> MCPPrincipal:
    """Resolve an MCP principal from a bearer JWT.

    JWT claims are verified server-side and only their expected, typed values are
    used to construct the principal.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise PermissionError("Invalid or missing JWT")

    token = authorization_header.removeprefix("Bearer ")
    if not token:
        raise PermissionError("Invalid or missing JWT")

    try:
        payload = verify_token(token, secret_key)
        user_id = payload["sub"]
        role = payload["role"]
        workspace_ids = payload["workspace_ids"]
        if (
            not isinstance(user_id, str)
            or not isinstance(role, str)
            or not isinstance(workspace_ids, list)
            or not all(isinstance(workspace_id, str) for workspace_id in workspace_ids)
        ):
            raise ValueError("Invalid JWT payload")
    except (AuthenticationError, KeyError, TypeError, ValueError) as exc:
        raise PermissionError("Invalid or missing JWT") from exc

    normalized_workspace_ids = tuple(workspace_ids)
    if role == "admin" and not normalized_workspace_ids:
        normalized_workspace_ids = ("*",)

    return MCPPrincipal(
        user_id=user_id,
        role=role,
        workspace_ids=normalized_workspace_ids,
    )
