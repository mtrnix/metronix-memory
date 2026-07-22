"""Optional JWT auth middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from metronix.auth.jwt import verify_token
from metronix.core.config import Settings
from metronix.mcp.auth import authenticate_http_request
from metronix.mcp.principal import bind_principal, reset_principal

PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/metrics/reset",
    "/api/v1/auth/login",
    "/api/v1/config",
    "/v1/models",
    "/v1/chat/completions",
    "/v1/proxy/chat/completions",
    "/v1/openapi.json",
}

# MCP routes authenticated separately from the REST API routes below.
MCP_PATHS = {"/mcp"}


async def _authenticate_personal_api_key(request: Request, token: str) -> dict[str, object] | None:
    """Resolve a stored personal API key to an active REST principal."""
    api_key_store = getattr(request.app.state, "api_key_store", None)
    user_store = getattr(request.app.state, "user_store", None)
    if api_key_store is None or user_store is None:
        return None

    # An empty static key prevents METRONIX_OPENAI_COMPAT_KEY from
    # authenticating a REST request.
    resolved = await api_key_store.resolve_key(token, static_key="")
    if resolved is None or resolved.get("source") != "personal":
        return None

    user = await user_store.get_user_by_id(str(resolved["user_id"]))
    if user is None or not user.get("is_active", True):
        return None

    role = str(user.get("role", "viewer"))
    workspace_ids = list(user.get("workspace_ids", []) or [])
    if role == "admin" and not workspace_ids:
        workspace_ids = ["*"]
    return {
        "user_id": str(user["id"]),
        "role": role,
        "workspace_ids": workspace_ids,
        "email": str(user.get("email", "") or ""),
    }


class OptionalAuthMiddleware(BaseHTTPMiddleware):
    """When AUTH_ENABLED=true, require JWT on protected API and MCP endpoints."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        settings: Settings = request.app.state.settings

        # Always initialise so downstream middleware never gets AttributeError.
        request.state.user = {}

        path = request.url.path.rstrip("/")

        # MCP must receive the same server-derived principal as standalone HTTP.
        # In development, retain the trusted request path used when auth is disabled.
        if path in MCP_PATHS:
            try:
                principal = authenticate_http_request(
                    request.headers.get("authorization"),
                    auth_enabled=settings.auth_enabled,
                    secret_key=settings.secret_key,
                )
            except PermissionError:
                detail = (
                    "MCP JWT authentication required"
                    if settings.auth_enabled
                    else "Invalid or missing MCP API key"
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": detail},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if principal is None:
                return await call_next(request)

            request.state.user = {
                "user_id": principal.user_id,
                "role": principal.role,
                "workspace_ids": list(principal.workspace_ids),
            }
            principal_token = bind_principal(principal)
            try:
                return await call_next(request)
            finally:
                reset_principal(principal_token)

        if not settings.auth_enabled:
            # AUTH off == dev mode == trusted admin. Without this, resolve_workspace_id
            # would 403 every ?workspace_id call (empty workspace_ids -> no access),
            # breaking local development. Mirrors the legacy login fallback that issues
            # `["*"]` for the shared-password admin.
            request.state.user = {
                "user_id": "anon",
                "role": "admin",
                "workspace_ids": ["*"],
                "email": "",
            }
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
            personal_api_key_user = await _authenticate_personal_api_key(request, token)
            if personal_api_key_user is not None:
                request.state.user = personal_api_key_user
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        role = payload.get("role", "viewer")
        workspace_ids = payload.get("workspace_ids", []) or []
        # Tolerate older admin tokens issued before login-time normalisation —
        # an empty workspace_ids on an admin role means "no per-workspace confinement",
        # which is equivalent to ``["*"]``. Non-admin empty stays empty (-> 403 in resolver).
        if role == "admin" and not workspace_ids:
            workspace_ids = ["*"]

        request.state.user = {
            "user_id": payload["sub"],
            "role": role,
            "workspace_ids": workspace_ids,
            "email": payload.get("email", ""),
        }

        return await call_next(request)
