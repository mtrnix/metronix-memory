# User Store Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single shared password with per-user accounts — PostgreSQL users table, bcrypt auth, CRUD API, seed admin on first boot.

**Architecture:** `UserStore` class in `src/metatron/auth/user_store.py` owns all DB operations. Login endpoint switches from `AUTH_PASSWORD` check to DB lookup + bcrypt verify, with backward-compat fallback. JWT payload gains `email` field. Admin user seeded on startup if table is empty.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (async), bcrypt, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-17-user-store-design.md`

**Repo:** metatron-core at `/Users/sm/Projects/metatron/metatron_mvp/metatroncore`

---

## File Map

### New Files

| File | Purpose |
|------|---------|
| `src/metatron/auth/passwords.py` | `hash_password()`, `verify_password()` (bcrypt) |
| `src/metatron/auth/user_store.py` | UserStore class: schema, CRUD, seed_admin |
| `src/metatron/api/routes/users.py` | User CRUD endpoints (admin-only) |

### Modified Files

| File | Change |
|------|--------|
| `src/metatron/auth/jwt.py` | Add `email` param to `create_token()` |
| `src/metatron/api/middleware.py` | Add `email` to `request.state.user` |
| `src/metatron/api/routes/auth.py` | New login flow + backward compat + update `/auth/me` |
| `src/metatron/api/app.py` | Register users router, seed admin on startup |

### UI Files (minimal changes)

| File | Change |
|------|--------|
| `src/api/types.ts` (metatron-ui) | Add `email`, `display_name` to LoginResponse |
| `src/components/auth/LoginPage.tsx` (metatron-ui) | Add email input |
| `src/stores/auth.ts` (metatron-ui) | Store email, displayName |

---

## Task 1: Password utilities

**Files:**
- Create: `src/metatron/auth/passwords.py`

- [ ] **Step 1: Create passwords module**

```python
"""Password hashing utilities using bcrypt."""
from __future__ import annotations

import bcrypt

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (cost factor 12)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def validate_password(password: str) -> None:
    """Raise ValueError if password doesn't meet requirements."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
```

- [ ] **Step 2: Verify bcrypt is installed**

Run: `cd /Users/sm/Projects/metatron/metatron_mvp/metatroncore && .venv/bin/python -c "import bcrypt; print(bcrypt.__version__)"`

If not installed: `.venv/bin/pip install bcrypt`

- [ ] **Step 3: Commit**

```bash
git add src/metatron/auth/passwords.py
git commit -m "feat: add bcrypt password hashing utilities"
```

---

## Task 2: UserStore — schema + CRUD

**Files:**
- Create: `src/metatron/auth/user_store.py`

- [ ] **Step 1: Create UserStore**

```python
"""PostgreSQL-backed user store with bcrypt authentication.

Tables:
    users            — user accounts (email, password_hash, role)
    user_workspaces  — workspace membership
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from metatron.auth.passwords import hash_password

logger = structlog.get_logger(__name__)


class UserStore:
    """CRUD for user accounts and workspace membership."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ensure_schema(self) -> None:
        """Create users and user_workspaces tables if they don't exist."""
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id            TEXT PRIMARY KEY,
                        email         TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        display_name  TEXT NOT NULL DEFAULT '',
                        role          TEXT NOT NULL DEFAULT 'viewer',
                        is_active     BOOLEAN NOT NULL DEFAULT true,
                        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at    TIMESTAMPTZ
                    )
                """))
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS user_workspaces (
                        user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        workspace_id TEXT NOT NULL,
                        joined_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, workspace_id)
                    )
                """))
            else:
                # SQLite (tests)
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id            TEXT PRIMARY KEY,
                        email         TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        display_name  TEXT NOT NULL DEFAULT '',
                        role          TEXT NOT NULL DEFAULT 'viewer',
                        is_active     INTEGER NOT NULL DEFAULT 1,
                        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at    TEXT
                    )
                """))
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS user_workspaces (
                        user_id      TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        joined_at    TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (user_id, workspace_id)
                    )
                """))
        logger.info("user_store.schema.ensured", dialect=dialect)

    # -- Users ---------------------------------------------------------------

    async def create_user(
        self,
        email: str,
        password: str,
        display_name: str = "",
        role: str = "viewer",
        workspace_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        user_id = str(uuid4())
        pw_hash = hash_password(password)
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO users (id, email, password_hash, display_name, role)
                    VALUES (:id, :email, :pw_hash, :display_name, :role)
                """),
                {"id": user_id, "email": email, "pw_hash": pw_hash,
                 "display_name": display_name, "role": role},
            )
            for ws_id in (workspace_ids or []):
                await conn.execute(
                    text("""
                        INSERT INTO user_workspaces (user_id, workspace_id)
                        VALUES (:uid, :ws)
                    """),
                    {"uid": user_id, "ws": ws_id},
                )
        logger.info("user_store.user.created", email=email, role=role)
        return {"id": user_id, "email": email, "display_name": display_name,
                "role": role, "is_active": True,
                "workspace_ids": workspace_ids or []}

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT id, email, password_hash, display_name, role, is_active, created_at FROM users WHERE email = :email"),
                {"email": email},
            )).first()
            if not row:
                return None
            user = dict(row._mapping)
            user["workspace_ids"] = await self.get_user_workspaces(user["id"])
            return user

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT id, email, display_name, role, is_active, created_at, updated_at FROM users WHERE id = :id"),
                {"id": user_id},
            )).first()
            if not row:
                return None
            user = dict(row._mapping)
            user["workspace_ids"] = await self.get_user_workspaces(user_id)
            return user

    async def list_users(
        self, limit: int = 50, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        async with self._engine.connect() as conn:
            total_row = (await conn.execute(text("SELECT COUNT(*) FROM users"))).scalar()
            rows = await conn.execute(
                text("SELECT id, email, display_name, role, is_active, created_at FROM users ORDER BY created_at LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset},
            )
            users = []
            for row in rows:
                user = dict(row._mapping)
                user["workspace_ids"] = await self.get_user_workspaces(user["id"])
                users.append(user)
            return users, total_row or 0

    async def update_user(self, user_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return await self.get_user_by_id(user_id)
        # Handle password separately
        if "password" in fields:
            fields["password_hash"] = hash_password(fields.pop("password"))
        allowed = {"email", "password_hash", "display_name", "role", "is_active"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return await self.get_user_by_id(user_id)
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = user_id
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                set_clause += ", updated_at = NOW()"
            else:
                set_clause += ", updated_at = datetime('now')"
            result = await conn.execute(
                text(f"UPDATE users SET {set_clause} WHERE id = :id"),
                updates,
            )
            if result.rowcount == 0:
                return None
        return await self.get_user_by_id(user_id)

    async def delete_user(self, user_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": user_id},
            )
            return result.rowcount > 0

    # -- Workspaces ----------------------------------------------------------

    async def get_user_workspaces(self, user_id: str) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT workspace_id FROM user_workspaces WHERE user_id = :uid"),
                {"uid": user_id},
            )
            return [r[0] for r in rows]

    async def add_workspace(self, user_id: str, workspace_id: str) -> None:
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                await conn.execute(
                    text("""
                        INSERT INTO user_workspaces (user_id, workspace_id)
                        VALUES (:uid, :ws) ON CONFLICT DO NOTHING
                    """),
                    {"uid": user_id, "ws": workspace_id},
                )
            else:
                await conn.execute(
                    text("""
                        INSERT OR IGNORE INTO user_workspaces (user_id, workspace_id)
                        VALUES (:uid, :ws)
                    """),
                    {"uid": user_id, "ws": workspace_id},
                )

    async def remove_workspace(self, user_id: str, workspace_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM user_workspaces WHERE user_id = :uid AND workspace_id = :ws"),
                {"uid": user_id, "ws": workspace_id},
            )

    # -- Seed ----------------------------------------------------------------

    async def seed_admin(self, password: str) -> dict[str, Any] | None:
        """Create initial admin user if users table is empty.

        Uses ON CONFLICT to handle multi-replica race conditions.
        """
        async with self._engine.connect() as conn:
            count = (await conn.execute(text("SELECT COUNT(*) FROM users"))).scalar()
            if count and count > 0:
                return None

        user = await self.create_user(
            email="admin@metatron.local",
            password=password,
            display_name="Admin",
            role="admin",
        )
        # Add to all existing workspaces
        try:
            async with self._engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT workspace_id FROM workspaces"),
                )
                for row in rows:
                    await self.add_workspace(user["id"], row[0])
                user["workspace_ids"] = await self.get_user_workspaces(user["id"])
        except Exception:
            # workspaces table might not exist yet
            pass

        logger.info("user_store.admin.seeded", email="admin@metatron.local")
        return user
```

- [ ] **Step 2: Commit**

```bash
git add src/metatron/auth/user_store.py
git commit -m "feat: add UserStore with CRUD and seed_admin"
```

---

## Task 3: Update JWT + middleware

**Files:**
- Modify: `src/metatron/auth/jwt.py`
- Modify: `src/metatron/api/middleware.py`

- [ ] **Step 1: Add email to create_token**

In `src/metatron/auth/jwt.py`, update `create_token` signature and payload:

```python
def create_token(
    user_id: str,
    role: str,
    workspace_ids: list[str],
    secret_key: str,
    expiry_hours: int = DEFAULT_EXPIRY_HOURS,
    email: str = "",
) -> str:
```

Add to payload dict:
```python
    if email:
        payload["email"] = email
```

- [ ] **Step 2: Add email to middleware user context**

In `src/metatron/api/middleware.py`, update the `request.state.user` dict (line 55-59):

```python
        request.state.user = {
            "user_id": payload["sub"],
            "role": payload.get("role", "viewer"),
            "workspace_ids": payload.get("workspace_ids", []),
            "email": payload.get("email", ""),
        }
```

- [ ] **Step 3: Commit**

```bash
git add src/metatron/auth/jwt.py src/metatron/api/middleware.py
git commit -m "feat: add email to JWT payload and middleware user context"
```

---

## Task 4: Update login + /auth/me

**Files:**
- Modify: `src/metatron/api/routes/auth.py`
- Modify: `src/metatron/api/app.py`

- [ ] **Step 1: Rewrite auth.py**

Replace `src/metatron/api/routes/auth.py` with:

```python
"""Auth API — login and session endpoints."""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from metatron.auth.jwt import create_token
from metatron.auth.passwords import verify_password
from metatron.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: Optional[str] = None
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    email: str = ""
    display_name: str = ""
    role: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate with email+password or legacy shared password."""
    settings = get_settings()

    # New flow: email + password → DB lookup
    if req.email:
        user_store = getattr(request.app.state, "user_store", None)
        if not user_store:
            raise HTTPException(status_code=500, detail="User store not available")

        user = await user_store.get_user_by_email(req.email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Account is disabled")

        if not verify_password(req.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        workspace_ids = user.get("workspace_ids", [])
        token = create_token(
            user_id=user["id"],
            role=user["role"],
            workspace_ids=workspace_ids,
            secret_key=settings.secret_key,
            expiry_hours=24,
            email=user["email"],
        )
        logger.info("auth.login.success", user_id=user["id"], email=user["email"])
        return LoginResponse(
            token=token,
            user_id=user["id"],
            email=user["email"],
            display_name=user.get("display_name", ""),
            role=user["role"],
        )

    # Legacy fallback: password only (no email)
    logger.warning("auth.login.legacy_fallback", hint="Use email+password instead")
    if req.password != settings.auth_password:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(
        user_id="admin",
        role="admin",
        workspace_ids=["*"],
        secret_key=settings.secret_key,
        expiry_hours=24,
    )
    return LoginResponse(token=token, user_id="admin", role="admin")


@router.get("/auth/me")
def me(request: Request) -> dict:
    """Return current user info from JWT."""
    user = getattr(request.state, "user", {})
    return {
        "status": "ok",
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "role": user.get("role", ""),
    }
```

- [ ] **Step 2: Register user_store on app.state and seed admin on startup**

In `src/metatron/api/app.py`, add to the `lifespan` function (in the startup section, after migrations):

```python
    # --- User store ---
    from metatron.auth.user_store import UserStore
    user_store = UserStore(create_async_engine(settings.postgres_dsn, pool_pre_ping=True))
    await user_store.ensure_schema()
    await user_store.seed_admin(settings.auth_password)
    app.state.user_store = user_store
```

Note: check the lifespan function structure — it may use `yield` pattern. Add user store init BEFORE the `yield`.

Also register users router alongside other routers:

```python
from metatron.api.routes import users
app.include_router(users.router, prefix="/api/v1")
```

- [ ] **Step 3: Commit**

```bash
git add src/metatron/api/routes/auth.py src/metatron/api/app.py
git commit -m "feat: per-user login with backward compat + seed admin on startup"
```

---

## Task 5: User CRUD endpoints

**Files:**
- Create: `src/metatron/api/routes/users.py`

- [ ] **Step 1: Create users router**

```python
"""User management API — admin only."""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from metatron.auth.passwords import validate_password

logger = structlog.get_logger()

router = APIRouter(tags=["users"])


def _require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    role: str = "viewer"
    workspace_ids: list[str] = []


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class AddWorkspaceRequest(BaseModel):
    workspace_id: str


@router.post("/users", status_code=201)
async def create_user(req: CreateUserRequest, request: Request) -> dict:
    _require_admin(request)
    validate_password(req.password)
    user_store = request.app.state.user_store
    try:
        user = await user_store.create_user(
            email=req.email,
            password=req.password,
            display_name=req.display_name,
            role=req.role,
            workspace_ids=req.workspace_ids,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email already exists")
        raise
    return user


@router.get("/users")
async def list_users(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    _require_admin(request)
    user_store = request.app.state.user_store
    users, total = await user_store.list_users(limit=limit, offset=offset)
    return {"users": users, "total": total}


@router.get("/users/{user_id}")
async def get_user(user_id: str, request: Request) -> dict:
    _require_admin(request)
    user_store = request.app.state.user_store
    user = await user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, request: Request) -> dict:
    caller = _require_admin(request)
    user_store = request.app.state.user_store

    updates = req.model_dump(exclude_none=True)

    # Lockout protection
    if caller.get("user_id") == user_id and "role" in updates:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    if "password" in updates:
        validate_password(updates["password"])

    user = await user_store.update_user(user_id, **updates)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request) -> None:
    caller = _require_admin(request)
    if caller.get("user_id") == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user_store = request.app.state.user_store
    if not await user_store.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")


@router.post("/users/{user_id}/workspaces", status_code=201)
async def add_workspace(user_id: str, req: AddWorkspaceRequest, request: Request) -> dict:
    _require_admin(request)
    user_store = request.app.state.user_store
    user = await user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user_store.add_workspace(user_id, req.workspace_id)
    return {"user_id": user_id, "workspace_id": req.workspace_id}


@router.delete("/users/{user_id}/workspaces/{workspace_id}", status_code=204)
async def remove_workspace(user_id: str, workspace_id: str, request: Request) -> None:
    _require_admin(request)
    user_store = request.app.state.user_store
    await user_store.remove_workspace(user_id, workspace_id)
```

- [ ] **Step 2: Commit**

```bash
git add src/metatron/api/routes/users.py
git commit -m "feat: add user CRUD endpoints (admin-only)"
```

---

## Task 6: UI changes — login with email

**Repo:** metatron-ui at `/Users/sm/Projects/metatron/metatron_mvp/metatronui`

**Files:**
- Modify: `src/api/types.ts`
- Modify: `src/components/auth/LoginPage.tsx`
- Modify: `src/stores/auth.ts`

- [ ] **Step 1: Update LoginResponse type**

In `src/api/types.ts`, update `LoginResponse`:

```typescript
export interface LoginResponse {
  token: string;
  user_id: string;
  email: string;
  display_name: string;
  role: string;
}
```

Update `LoginRequest`:

```typescript
export interface LoginRequest {
  email: string;
  password: string;
}
```

- [ ] **Step 2: Update auth store**

In `src/stores/auth.ts`, add `email` and `displayName`:

```typescript
interface AuthState {
  userId: string | null;
  email: string | null;
  displayName: string | null;
  role: string | null;
  isEnterprise: boolean | null;
  setAuth: (userId: string, role: string, email: string, displayName: string) => void;
  setIsEnterprise: (value: boolean) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  userId: null,
  email: null,
  displayName: null,
  role: null,
  isEnterprise: null,
  setAuth: (userId, role, email, displayName) =>
    set({ userId, role, email, displayName }),
  setIsEnterprise: (isEnterprise) => set({ isEnterprise }),
  clearAuth: () =>
    set({ userId: null, email: null, displayName: null, role: null, isEnterprise: null }),
}));
```

- [ ] **Step 3: Update login API call**

In `src/api/auth.ts`, update `login` function:

```typescript
export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password } satisfies LoginRequest),
  });
}
```

- [ ] **Step 4: Update LoginPage**

In `src/components/auth/LoginPage.tsx`:

Add email state:
```typescript
const [email, setEmail] = useState('');
```

Update handleSubmit:
```typescript
const res = await login(email, password);
setToken(res.token);
useAuthStore.getState().setAuth(res.user_id, res.role, res.email, res.display_name);
```

Add email input field before password input:
```tsx
<input
  type="email"
  value={email}
  onChange={(e) => setEmail(e.target.value)}
  placeholder="Email"
  className="w-full rounded-xl border border-border bg-bg px-4 py-3 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none"
/>
```

Update submit disabled check:
```typescript
disabled={loading || !password.trim() || !email.trim()}
```

- [ ] **Step 5: Build check**

Run: `cd /Users/sm/Projects/metatron/metatron_mvp/metatronui && npx vite build`

- [ ] **Step 6: Commit**

```bash
git add src/api/types.ts src/api/auth.ts src/stores/auth.ts src/components/auth/LoginPage.tsx
git commit -m "feat: login with email+password, store user info"
```

---

## Task 7: Final verification

- [ ] **Step 1: Restart backend, verify seed admin**

Restart backend. Logs should show:
```
user_store.schema.ensured  dialect=postgresql
user_store.admin.seeded    email=admin@metatron.local
```

- [ ] **Step 2: Test login via curl**

```bash
# New format
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@metatron.local","password":"metatron"}'

# Legacy format (backward compat)
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"metatron"}'
```

Both should return tokens.

- [ ] **Step 3: Test user CRUD**

```bash
TOKEN=...  # from login
# List users
curl -s http://localhost:8000/api/v1/users -H "Authorization: Bearer $TOKEN"
# Create user
curl -s -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@test.com","password":"password123","display_name":"Bob","role":"editor"}'
```

- [ ] **Step 4: Test UI login with email**

Open browser, login with `admin@metatron.local` / `metatron`.

- [ ] **Step 5: Commit any fixes**

If any fixes were needed, commit them.
