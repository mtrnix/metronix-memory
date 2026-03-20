"""Optional JWT auth middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from metatron.auth.jwt import verify_token
from metatron.core.config import Settings
from metatron.mcp.auth import validate_api_key

PUBLIC_PATHS = {
    "/health", "/ready", "/metrics", "/metrics/reset",
    "/api/v1/auth/login",
    "/api/v1/config",
    "/v1/models", "/v1/chat/completions", "/v1/openapi.json",
}

# Paths that use MCP API key auth instead of JWT
MCP_PATHS = {"/mcp"}


class OptionalAuthMiddleware(BaseHTTPMiddleware):
    """When AUTH_ENABLED=true, require JWT on /api/v1/ endpoints.

    The /mcp endpoint uses its own API key auth (METATRON_MCP_API_KEY)
    independently of AUTH_ENABLED.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        settings: Settings = request.app.state.settings

        # Always initialise so downstream middleware never gets AttributeError.
        request.state.user = {}

        path = request.url.path.rstrip("/")

        # MCP endpoint: validate via METATRON_MCP_API_KEY (independent of AUTH_ENABLED)
        if path in MCP_PATHS:
            auth_header = request.headers.get("authorization")
            if not validate_api_key(auth_header):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or missing MCP API key"},
                )
            return await call_next(request)

        if not settings.auth_enabled:
            return await call_next(request)

        if path in PUBLIC_PATHS:
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]
        try:
            payload = verify_token(token, settings.secret_key)
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.user = {
            "user_id": payload["sub"],
            "role": payload.get("role", "viewer"),
            "workspace_ids": payload.get("workspace_ids", []),
            "email": payload.get("email", ""),
        }

        return await call_next(request)
