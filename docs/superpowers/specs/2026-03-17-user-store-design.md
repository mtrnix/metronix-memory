# User Store & Per-User Accounts — Design Spec

**Date:** 2026-03-17
**Status:** Approved
**Scope:** metatron-core (backend only, UI minimal changes)

## Problem

Metatron uses a single shared password (`AUTH_PASSWORD`) for all users. There are no individual accounts, no user management, and no way to identify who performed an action. Enterprise RBAC groups require real user identities to function properly.

## Approach

PostgreSQL-backed user store with bcrypt password hashing. Replace single-password login with per-user email+password auth. Seed initial admin on first boot. Backward-compatible fallback for old login format.

---

## 1. Database

### Table: `users`

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'viewer',
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ
);
```

### Table: `user_workspaces`

```sql
CREATE TABLE user_workspaces (
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, workspace_id)
);
```

### Seed Admin

On first startup, if `users` table is empty:
- Email: `admin@metatron.local`
- Password: from `AUTH_PASSWORD` env var (default: `metatron`)
- Role: `admin`
- Workspaces: added to all existing workspaces
- Log: `"Initial admin user created: admin@metatron.local"`
- Uses `INSERT ... ON CONFLICT (email) DO NOTHING` to handle multi-replica race condition

---

## 2. Auth Flow

### Login — `POST /api/v1/auth/login`

**New request format:**
```json
{ "email": "admin@metatron.local", "password": "metatron" }
```

**Backward compat:** If `email` is absent and only `password` is present, fallback to old single-password behavior. This allows old UI clients to work until updated. Remove fallback in next major version.

**Important:** Login handler becomes `async def login(...)` (was sync) since it now requires DB queries.

**Flow:**
1. Lookup user by email in `users` table — 401 if not found
2. Check `is_active` — 403 if disabled
3. bcrypt verify password against `password_hash` — 401 if wrong
4. Fetch workspace_ids from `user_workspaces`
5. Create JWT with real user data
6. Return login response

### `GET /api/v1/auth/me`

Currently returns hardcoded `{"user_id": "admin", "role": "admin"}`. Updated to return real user data from `request.state.user`:

```json
{
  "user_id": "uuid",
  "email": "admin@metatron.local",
  "role": "admin"
}
```

**Login response:**
```json
{
  "token": "jwt...",
  "user_id": "uuid-string",
  "email": "admin@metatron.local",
  "display_name": "Admin",
  "role": "admin"
}
```

### JWT Payload

```json
{
  "sub": "uuid-user-id",
  "role": "admin",
  "email": "admin@metatron.local",
  "workspace_ids": ["MTRNIX", "OTHER"],
  "iat": 1234567890,
  "exp": 1234654290
}
```

Changes from current:
- `sub` → real user UUID (was hardcoded `"admin"`)
- `workspace_ids` → real list from `user_workspaces` (was `["*"]`)
- `email` → added for UI display

### Password Hashing

bcrypt via `bcrypt` package directly (actively maintained; `passlib` is unmaintained). Never plaintext, never simple hash.

```python
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())
```

### Password Validation

Minimum 8 characters. Enforced at create user and update password endpoints. No complexity rules (length is the primary security factor).

---

## 3. User CRUD API

All endpoints admin-only. Password hash never returned in responses.

Admin-only enforcement: routes self-check `request.state.user["role"] == "admin"` via a dependency (core feature, not enterprise RBAC). Returns 403 for non-admins.

### Endpoints

```
POST   /api/v1/users                                    — create user
GET    /api/v1/users?limit=50&offset=0                  — list users (paginated)
GET    /api/v1/users/{user_id}                          — get user
PATCH  /api/v1/users/{user_id}                          — update user
DELETE /api/v1/users/{user_id}                          — delete user
POST   /api/v1/users/{user_id}/workspaces               — add to workspace
DELETE /api/v1/users/{user_id}/workspaces/{workspace_id} — remove from workspace
```

### Create User — `POST /api/v1/users`

```json
{
  "email": "bob@company.com",
  "password": "secretpass",
  "display_name": "Bob Smith",
  "role": "editor",
  "workspace_ids": ["MTRNIX"]
}
```

- Password hashed with bcrypt before storage
- Email unique — 409 on duplicate
- `workspace_ids` optional — empty = no workspace access

### List Users — `GET /api/v1/users`

```json
{
  "users": [
    {
      "id": "uuid",
      "email": "admin@metatron.local",
      "display_name": "Admin",
      "role": "admin",
      "is_active": true,
      "workspace_ids": ["MTRNIX"],
      "created_at": "2026-03-17T..."
    }
  ],
  "total": 1
}
```

### Update User — `PATCH /api/v1/users/{user_id}`

Partial update — only provided fields:

```json
{
  "role": "viewer",
  "display_name": "New Name",
  "is_active": false
}
```

If `password` is provided (min 8 chars) — hash and update. `updated_at` set to `NOW()` on every update. Admin cannot demote their own role (lockout protection).

### Delete User — `DELETE /api/v1/users/{user_id}`

Returns 204. Admin cannot delete themselves. DB cascade removes from `user_workspaces`. Enterprise `enterprise_group_members` cleanup is application-level (no FK across repos) — enterprise plugin should subscribe to a `USER_DELETED` event or handle orphaned memberships gracefully.

### Workspace Membership

```
POST   /api/v1/users/{user_id}/workspaces
Body:  { "workspace_id": "MTRNIX" }

DELETE /api/v1/users/{user_id}/workspaces/{workspace_id}
```

---

## 4. File Structure

### New Files

| File | Purpose |
|------|---------|
| `src/metatron/auth/passwords.py` | `hash_password()`, `verify_password()` (bcrypt) |
| `src/metatron/auth/user_store.py` | UserStore class: CRUD, seed_admin() |
| `src/metatron/api/routes/users.py` | User CRUD endpoints router |

### Modified Files

| File | Change |
|------|--------|
| `src/metatron/api/routes/auth.py` | Login: email+password lookup, backward compat fallback |
| `src/metatron/api/app.py` | Register users router, call seed_admin() in startup |
| `src/metatron/api/middleware.py` | Add `email` to `request.state.user` dict: `"email": payload.get("email", "")` |
| `src/metatron/auth/jwt.py` | `create_token(user_id, role, workspace_ids, secret_key, expiry_hours, email="")`: add email param |
| `src/metatron/api/types.ts` (UI) | Add `email`, `display_name` to LoginResponse |
| `src/components/auth/LoginPage.tsx` (UI) | Add email input field |
| `src/stores/auth.ts` (UI) | Store email, display_name |

### UserStore Class

```python
class UserStore:
    def __init__(self, engine: AsyncEngine): ...
    async def ensure_schema(self): ...
    async def seed_admin(self, password: str): ...

    async def create_user(self, email, password, display_name, role, workspace_ids) -> dict
    async def get_user_by_email(self, email) -> dict | None
    async def get_user_by_id(self, user_id) -> dict | None
    async def list_users(self, limit, offset) -> tuple[list[dict], int]
    async def update_user(self, user_id, **fields) -> dict | None
    async def delete_user(self, user_id) -> bool

    async def add_workspace(self, user_id, workspace_id): ...
    async def remove_workspace(self, user_id, workspace_id): ...
    async def get_user_workspaces(self, user_id) -> list[str]
```

---

## 5. Backward Compatibility

- **Old login format** (`{ password: "metatron" }`) — works via fallback, logs deprecation warning
- **Existing JWT tokens** — remain valid until expiry (same signing key)
- **AUTH_PASSWORD env var** — still used for seed admin password
- **Enterprise RBAC** — `request.state.user.user_id` changes from `"admin"` to UUID string. Enterprise middleware already handles string user_ids. **Migration note:** existing `enterprise_role_assignments` rows with `user_id = "admin"` need re-keying to the new UUID after migration.
- **`workspace_ids: ["*"]`** — admin seed user gets all workspaces explicitly, not `["*"]`. `OptionalAuthMiddleware` keeps wildcard expansion as fallback: if `workspace_ids` contains `"*"`, treat as "all workspaces". This ensures old tokens still work.

---

## 6. Security

- Passwords stored as bcrypt hashes (cost factor 12)
- Password hash never in API responses, never in logs
- Admin cannot delete themselves or demote their own role
- `is_active: false` blocks login immediately
- Rate limiting on login already exists via enterprise middleware
- Email validation: basic format check, not uniqueness across workspaces (globally unique)

---

## 7. Future (deferred)

- **Password reset flow** — email-based reset token
- **Per-workspace roles** — different role in each workspace via `user_workspaces.role`
- **Enterprise user dropdown** — GroupDetail "Add member" uses `GET /api/v1/users` instead of text input
- **User profile page** — self-service display_name and password change
- **OAuth/social login** — alternative to email+password
