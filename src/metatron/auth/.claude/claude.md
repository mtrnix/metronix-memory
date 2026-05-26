# Auth

## Overview
L3 — authentication and authorization. Two parallel auth models live here:

1. **Built-in JWT** (`jwt.py`, `dependencies.py`) — HS256 tokens issued by `/api/v1/auth/login`,
   verified by `OptionalAuthMiddleware`. Role hierarchy (viewer < editor < admin). Supports
   plugin-provided backends (SAML, OIDC) via `PluginManager.get_auth_provider()`.
2. **ASOC session auth** (`asoc_session.py`, MTRNIX-370) — `X-ASOC-Session` header for chat
   endpoints + static `Authorization: Bearer <ASOC_ADMIN_TOKEN>` for admin endpoints. No JWT.

The two models are completely independent — built-in JWT auth still drives the legacy
Open WebUI / `/api/v1/chat` flows; ASOC session auth gates only `/api/v1/asoc/*`.

## Files

### `jwt.py`
`create_token(user_id, role, workspace_ids, secret_key, expiry_hours=24) -> str`
— HS256 JWT. Payload: `sub`, `role`, `workspace_ids`, `iat`, `exp`.

`verify_token(token, secret_key) -> dict`
— Decodes and validates JWT. Raises `AuthenticationError` on `ExpiredSignatureError`
or any `InvalidTokenError`. Returns decoded payload dict.

### `rbac.py`
Role hierarchy: `_ROLE_LEVELS = {VIEWER: 0, EDITOR: 1, ADMIN: 2}`.

`check_permission(user_role, required_role) -> bool` — numeric comparison.
`require_role(user_role, required_role)` — raises `AuthenticationError` if insufficient.

### `dependencies.py`
FastAPI `Depends()` helpers for built-in-JWT route protection.

**Auth resolution order in `get_current_user()`:**
1. Check `request.app.state.plugin_manager.get_auth_provider()`
2. If plugin provider exists → `await provider.authenticate(token)`
3. Fallback → `jwt.verify_token()` + build `User` from payload

`require_admin(user)` — wraps `get_current_user`, raises 403 if role < ADMIN.
`require_editor(user)` — wraps `get_current_user`, raises 403 if role < EDITOR.

`AuthenticationError` from core layers is converted to `HTTPException 401` here —
never leaks raw exceptions to HTTP responses.

### `asoc_session.py` (MTRNIX-370 Phase 2a)
Session-id-based auth for the ASOC pilot. Replaces the deleted `asoc_jwt.py` HS256 verifier.

**`AsocAuthContext`** — frozen dataclass returned by `asoc_chat_auth`:
`session_id`, `user_id`, `username`, `display_name`, `email`, `roles`.

**`AsocSessionAuth`** — validator with in-process TTL cache.
- Header: `X-ASOC-Session: <session_id>`.
- On cache miss: calls `asoc_get_current_user` MCP tool via user-mode `AsocMcpClient`
  (Option B from the ASOC contract §3.1 — uses the same session_id ASOC issued).
- Cache TTL: `METATRON_ASOC_SESSION_CACHE_TTL_SECONDS` (default 3600).
- Soft cap 10 000 entries; evicts oldest 25 % when exceeded.
- On `McpAuthError` → 401 `invalid_or_expired_session`; on `McpUnavailableError` /
  `McpProtocolError` → 503 `asoc_unavailable`.

**`asoc_chat_auth(request)` → `AsocAuthContext`** — FastAPI dependency used by all
chat / thread endpoints under `/api/v1/asoc/chat/*`. Returns 503 if
`app.state.asoc_session_auth` was not configured at startup.

**`asoc_admin_auth(request)` → `None`** — FastAPI dependency used by workspace lifecycle
endpoints (`POST /workspace/bootstrap`, `DELETE /workspace/{id}`, `GET /workspace/{id}/status`)
and the user-cascade-delete endpoint. Constant-time compares the `Authorization: Bearer ...`
header against `settings.asoc_admin_token`. Empty configured token → 503
`asoc_admin_token_not_configured` (fail-closed). Mismatched token → 401.

### `user_mapping.py`
`PlatformUserMapper` — resolves channel identities (Telegram/Slack/Discord) to internal Users.
Uses `user_platform_mappings` table (migration 010).

Key methods:
- `resolve(platform, platform_user_id, display_name, auto_create) -> User | None` — looks up mapping, auto-creates User if not found
- `create_mapping(user_id, platform, platform_user_id, display_name)` — explicit mapping creation
- `list_mappings()` — list all mappings
- `get_user_mappings(user_id)` — mappings for a specific user
- `update_mapping(user_id, platform, platform_user_id, display_name)` — update existing
- `delete_mapping(user_id, platform, platform_user_id)` — remove mapping

Results cached with 30-second TTL (`_CACHE_TTL_SECONDS`).

### `user_store.py`
`UserStore` — User CRUD against PostgreSQL.
Used by `user_mapping.py` for auto-creating users.

### `api_key_store.py`
Personal API key management (`mtk_...` format) for OpenAI-compat endpoints.

## Key Patterns
- **`AuthenticationError` stays internal** — only converted to `HTTPException` at the API boundary (dependencies.py), never in jwt.py or rbac.py
- **Plugin-first auth** — `get_current_user` checks plugin provider before JWT fallback; enterprise SAML/OIDC drops in without touching core
- **Stateless JWT** — built-in JWT carries `sub` / `role` / `workspace_ids` in the token payload
- **Cached ASOC session** — ASOC sessions are validated once via MCP and cached in-process;
  invalidation is purely TTL-driven, no server-push channel
- **`AUTH_ENABLED=false` by default** — `OptionalAuthMiddleware` skips built-in JWT validation
  unless explicitly enabled. The ASOC dependencies are gated by `app.state.asoc_session_auth`
  / `settings.asoc_admin_token` and operate independently of `AUTH_ENABLED`.

## Dependencies
- **Depends on**: `core.exceptions` (AuthenticationError), `core.models` (User, Role), `core.config` (Settings), `storage.postgres` (PostgresStore, used by user_mapping), `integrations.asoc_mcp_client` (AsocMcpClient — used by `asoc_session.py` for Option B validation)
- **Depended on by**: `api.middleware` (OptionalAuthMiddleware uses jwt.verify_token), `api.dependencies` (get_current_user), `api.routes.auth` (login endpoint), `api.routes.asoc_chat` + `api.routes.asoc_workspace` + `api.routes.users` (ASOC dependencies)
