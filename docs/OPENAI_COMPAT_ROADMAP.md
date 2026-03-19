# Tech Debt: Unify API to OpenAI Standard and Integrate RBAC with Open WebUI

## Context

An OpenAI-compatible API (`/v1/models`, `/v1/chat/completions`) has been implemented for Open WebUI integration. In parallel, RBAC with per-user authorization has been merged. Currently there are two parallel chat interfaces and a static API key with no user binding.

Goal — eliminate duplication, make the OpenAI format the sole chat interface, and link Open WebUI users with Metatron RBAC.

---

## Block 1: Migrate Admin UI to OpenAI-Compatible API

### Current State
- Admin UI uses `/api/v1/chat` (sync) and `/api/v1/chat/stream` (SSE with custom events: `status`, `chunk`, `sources`, `done`)
- OpenAI-compat: `/v1/chat/completions` (SSE with `delta` chunks in OpenAI format)
- Two different request/response formats, two separate history stores

### Action Items

1. **Switch admin frontend to `/v1/chat/completions`**
   - Replace SSE client: instead of custom events (`chunk`, `sources`, `done`), parse OpenAI delta format
   - Request: instead of `{question, workspace_id, user_id}`, send `{model: "metatron-rag-{ws}", messages: [{role: "user", content: "..."}]}`
   - Sources: currently arrive as a separate SSE event `sources` — in OpenAI format they are embedded in the response text as markdown. The frontend already parses `[$[title]$]` markers — ensure markdown links also render correctly

2. **File upload**
   - `/api/v1/upload` stays as-is (OpenAI format does not cover file ingestion)
   - Consider a `/v1/files` endpoint analogous to the OpenAI Files API — for the future

3. **Remove legacy endpoints**
   - Remove `/api/v1/chat` and `/api/v1/chat/stream`
   - Remove duplicate in-memory history from `chat.py`
   - Keep one history store in `openai_compat.py` (or extract to a shared module)

4. **Update channels (Telegram, Discord, Slack)**
   - Bots currently call `hybrid_search_and_answer()` directly — this is fine, they don't go through HTTP
   - But their in-memory history in `chat.py` is tied to the same dict — decide whether to migrate channels to a shared history store or leave as-is

### Migration Order
1. Frontend switches to `/v1/chat/completions` (both endpoints live in parallel)
2. Verify everything works
3. Remove legacy endpoints

---

## Block 2: Open WebUI User Mapping → Metatron RBAC

### Current State
- Open WebUI: own user database (email + password, or OAuth/LDAP)
- Metatron: own user database after RBAC (`UserStore`, bcrypt, roles viewer/editor/admin)
- OpenAI-compat API: static `METATRON_OPENAI_COMPAT_KEY`, all requests come from one "user"
- The `user` field in OpenAI requests is currently only logged

### Target Architecture

Both services maintain their own user databases. Mapping between them is by email or external identifier.

```
Open WebUI (user: john@company.com)
  → POST /v1/chat/completions { user: "john@company.com" }
  → Metatron resolves john@company.com → Metatron User (role, workspace_ids)
  → Filters response by permissions
```

### Action Items

1. **Replace static API key with per-user tokens**
   - Option A: Open WebUI sends a Metatron JWT in the `Authorization: Bearer <metatron-jwt>` header — requires Open WebUI to obtain a JWT for each user
   - Option B: Open WebUI sends a service key + `user` field with identifier — Metatron resolves the user by the `user` field. Simpler to implement
   - Option C: Shared OAuth/OIDC provider (Keycloak, etc.) — both services validate the same token. Most correct for enterprise
   - **Recommendation**: start with Option B (service key + user field), then migrate to C for enterprise

2. **Implement user → Metatron User resolution in OpenAI-compat**
   - In `verify_openai_compat_key` or a separate dependency — look up the user from the `user` field in `UserStore`
   - If not found — either 403, or auto-provision (create with viewer role)
   - Place the resolved user into `request.state.user` — standard RBAC from there

3. **Filter workspaces by permissions**
   - `GET /v1/models` — return only workspaces accessible to the user
   - Current: all workspaces without filtering
   - After: `workspace_ids` from JWT/user profile → filter

4. **User synchronization**
   - With Option B: need a mechanism to create users in Metatron on first request from Open WebUI (auto-provision)
   - Mapping: `Open WebUI email` → `Metatron user_id` (or by email directly)
   - Roles: default role for auto-provisioned users (viewer), admin assigns roles manually

5. **Audit and history**
   - Bind OpenAI-compat requests to a specific user (not `"openai-default"`)
   - Query traces in PostgreSQL — record real user_id
   - Conversation history — keyed by real user_id

### Open Questions

- Is auto-provisioning users needed, or only manual creation via admin panel?
- How to handle deleted/blocked users — Open WebUI doesn't know a user is deactivated in Metatron
- Is bidirectional sync (Metatron → Open WebUI) needed, or only one-way?

---

## Block 3: Consolidate Conversation History

### Current State
- `chat.py`: in-memory dict, used by legacy endpoints and channels
- `openai_compat.py`: separate in-memory dict, used by OpenAI-compat
- Both are volatile (lost on restart)

### Action Items

1. **Extract history into a shared module** (`api/history.py` or `storage/conversation.py`)
2. **Single store for all channels** — HTTP, OpenAI-compat, Telegram, Discord, Slack
3. **Persistence** — migrate from in-memory to PostgreSQL (`conversations` table)
4. **Per-user scoping** — history bound to user_id from RBAC, not an arbitrary string

---

## Priorities

| # | Task | Dependencies | Priority |
|---|------|-------------|----------|
| 1 | Migrate frontend to `/v1/chat/completions` | None | High |
| 2 | Remove legacy chat endpoints | Block 1 complete | Medium |
| 3 | User field → Metatron RBAC mapping (Option B) | RBAC stable | High |
| 4 | Filter `/v1/models` by permissions | Block 3 | High |
| 5 | Consolidate history into shared module | Block 2 | Medium |
| 6 | Persistent history in PostgreSQL | Block 5 | Low |
| 7 | OAuth/OIDC integration (Option C) | Enterprise roadmap | Low |
