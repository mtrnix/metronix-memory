"""MCP HTTP authentication middleware.

Provides API key validation for HTTP transport.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional

import structlog

logger = structlog.get_logger()


def get_api_key() -> Optional[str]:
    """Get the configured API key from environment.

    Returns:
        API key string if configured, None otherwise.
    """
    return os.environ.get("METATRON_MCP_API_KEY")


def validate_api_key(authorization_header: Optional[str]) -> bool:
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


def require_api_key(authorization_header: Optional[str]) -> None:
    """Require a valid API key, raising an exception if invalid.

    Args:
        authorization_header: The Authorization header value

    Raises:
        PermissionError: If the API key is invalid
    """
    if not validate_api_key(authorization_header):
        raise PermissionError("Invalid or missing API key")
