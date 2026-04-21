# Connecting Hermes Agent to Metatron

This guide explains how to wire [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(NousResearch) to Metatron Core so that Hermes can use Metatron as a knowledge
backend and — partially — as a memory layer.

Hermes is our **primary external agent runtime**. Metatron is designed to be
consumed by runtimes like Hermes rather than to ship its own chat UI.

## TL;DR

Three integration levels, pick one:

| Level | How | What works | Effort |
|---|---|---|---|
| **1. MCP server** (recommended) | Add Metatron MCP server to Hermes config | Document RAG read/write via tools `metatron_search`, `metatron_store`, etc. | 5 minutes |
| **2. OpenAI-compat proxy** | Point Hermes at `https://<metatron>/v1` as an LLM provider | Hermes asks questions, Metatron answers from corporate KB (RAG-backed) | 2 minutes |
| **3. Custom Hermes skill for agent memory** | Write a Hermes skill that calls `/api/v1/memory/*` | Full read/write of agent memory records | 1–2 days |

Level 1 is the right default today. Levels 2 and 3 layer on top.

## What works right now

- ✅ MCP server at `/mcp` with twelve tools — five document-oriented
  (`metatron_search`, `metatron_get`, `metatron_store`, `metatron_sync`, `metatron_status`),
  one fast-retrieval (`metatron_search_fast`), and six memory-oriented
  (`metatron_memory_search`, `metatron_memory_store`, `metatron_memory_batch_store`,
  `metatron_memory_list`, `metatron_memory_update`, `metatron_memory_delete`).
- ✅ OpenAI-compatible endpoint at `/v1/chat/completions` that answers by running
  `hybrid_search_and_answer` over a workspace.
- ✅ Memory REST API at `/api/v1/memory/*` (create, search, list, delete records).
- ✅ Auth via `METATRON_MCP_API_KEY` (MCP) or `mtk_...` / `METATRON_OPENAI_COMPAT_KEY` (OAI).
- ✅ Workspace isolation — every call scoped by `workspace_id`.

## What does NOT work yet

- ❌ **Memory context is not auto-injected into `/v1/chat/completions`.** The OAI endpoint
  does RAG over documents but does not pull agent memory into the system prompt
  (MTRNIX-275, backlog).
- ❌ **Dialogue write-back.** Metatron does not yet extract facts from Hermes replies
  into assertion memory. Planned as part of the assertion lifecycle layer.
- ❌ **Agent registry.** Metatron does not yet have a first-class agent record —
  Hermes instances are identified by API key only. Multiple Hermes processes with
  the same key are indistinguishable.

These gaps are tracked in Jira (MTRNIX-249, MTRNIX-272, MTRNIX-275, WS4 tickets)
and documented in `docs/LEGACY.md` and the `metatron-arch-guard` skill.

## Prerequisites

- Metatron Core running (typically `docker compose up -d && make dev` locally, or a
  deployed instance).
- Workspace created with at least one connector synced (Confluence, Jira, etc.)
  so there is content to search.
- Hermes installed (`curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash`).

## Level 1 — MCP integration (recommended)

### 1. Configure Metatron

```bash
# .env
METATRON_MCP_API_KEY=your-secure-key
```

Without this key the `/mcp` endpoint would accept unauthenticated requests.

### 2. Ensure `/mcp` is reachable

Metatron mounts MCP over streamable-HTTP at `/mcp` on the same port as the API
(default 8000). If you front Metatron with nginx/Caddy, explicitly proxy `/mcp`:

**Caddy:**
```caddyfile
handle /mcp {
    reverse_proxy metatron-backend:8000
}
```

**nginx:**
```nginx
location /mcp {
    proxy_pass http://metatron-backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Without the rule, your proxy may serve the SPA for unknown paths and block MCP POSTs.

### 3. Verify

```bash
curl -X POST -H "Authorization: Bearer your-secure-key" https://<metatron>/mcp
```

A response (even an MCP protocol error) confirms the endpoint is reachable and the
key is valid. A `401` means the key is wrong; a `405 Not Allowed` from nginx means
the reverse proxy is not configured for `/mcp`.

### 4. Add Metatron to Hermes

Hermes supports MCP natively via its `MCP Integration` feature — see
[Hermes MCP docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp).

Edit Hermes config (via `hermes config set` or the config file — check
`hermes config path`):

```toml
[mcp_servers.metatron]
url = "https://<metatron-host>/mcp"
headers = { Authorization = "Bearer your-secure-key" }
```

Restart Hermes (`hermes` / `hermes gateway restart`).

### 5. Verify from Hermes

```bash
hermes
> /tools
# look for metatron_search, metatron_get, etc.
```

Ask a question that requires your corporate KB ("What is our refund policy?") —
Hermes should call `metatron_search` with an appropriate query and `workspace_id`.

### Available tools

| Tool | Purpose |
|---|---|
| `metatron_search` | Hybrid search: Qdrant dense + SPLADE sparse + Neo4j graph enrichment + reranker + LLM answer |
| `metatron_search_fast` | Low-latency passage lookup (dense + optional metadata). No rerank, no LLM answer. Target P50 <800 ms |
| `metatron_get` | Fetch full document by id |
| `metatron_store` | Index a new document (the agent publishes its own knowledge to KB) |
| `metatron_sync` | Trigger sync from registered MCP sources (not Jira/Confluence connectors) |
| `metatron_status` | Workspace statistics (doc count, last sync, etc.) |
| `metatron_memory_search` | Hybrid agent-memory search (Qdrant + Neo4j + Redis-session blend) |
| `metatron_memory_store` | Persist an agent memory record (per-agent / global / session scopes) |
| `metatron_memory_batch_store` | Persist multiple memory records in one call (max 100, sequential dedup) |
| `metatron_memory_list` | List all memory records for an agent with pagination and filters |
| `metatron_memory_update` | Update existing record in place (re-embeds only on content change) |
| `metatron_memory_delete` | Delete a persistent memory record by id |

For complete tool signatures, parameter tables, response schemas, and error codes
see **[MCP_API.md](MCP_API.md)**.

### Routing patterns

Four entry points cover different trade-offs between latency, recall, and scope:

| Use case | Tool | Why |
|---|---|---|
| "Answer my question from corporate KB" — need synthesized answer with citations | `metatron_search` | Full pipeline: hybrid recall + reranker + LLM. Slowest but highest-quality answer |
| "Fetch top-N raw passages fast" — agent will compose its own answer, or needs snippets for UI | `metatron_search_fast` | Dense + optional metadata only. No rerank / HyDE / graph / LLM. P50 <800 ms |
| "Recall what this agent knows about X" — agent-specific long-term memory | `metatron_memory_search` | Hybrid search over agent memory store (Qdrant + Neo4j + Redis-session blend) |
| "Remember this fact for next time" — write to agent memory | `metatron_memory_store` | Persists to PG + Qdrant + Neo4j (or Redis for session scope) with content dedup |

Rules of thumb:

- Default to `metatron_search_fast` for every lookup; upgrade to `metatron_search`
  only when the user explicitly needs a synthesized answer with citations.
- Keep `metatron_memory_*` strictly for agent-owned facts (what the agent learned,
  what the user told the agent). Corporate KB content belongs to `metatron_store`.
- `metatron_memory_delete` touches only the persistent stores — Redis-backed
  session records are managed via the session lifecycle API, not this tool.

### Finding your workspace_id

```bash
curl https://<metatron>/api/v1/workspaces
```

Hermes needs this to pass as the `workspace_id` argument of MCP tools.

## Level 2 — OpenAI-compat proxy

If you prefer Hermes to treat Metatron as a drop-in LLM provider (Hermes asks,
Metatron answers from your KB), configure Metatron as a custom provider:

```bash
hermes model
# provider: custom (OpenAI-compatible)
# base_url: https://<metatron>/v1
# api_key:  your mtk_... token  (or the static METATRON_OPENAI_COMPAT_KEY)
# model:    metatron-rag-<your-workspace-id>
```

Model id format is `metatron-rag-{workspace_id}`. Get available ids via:

```bash
curl -H "Authorization: Bearer <key>" https://<metatron>/v1/models
```

**What happens on each turn:**

1. Hermes builds its usual prompt (with Hermes-managed memory, persona, skills).
2. Sends it as an OpenAI `chat/completions` request to Metatron.
3. Metatron ignores most of the prompt, runs `hybrid_search_and_answer` on the
   workspace, and returns an OAI-format response built from retrieved documents.
4. Hermes treats the response as the "LLM output."

**Caveats:**

- This is NOT a raw LLM proxy. Metatron is the answering system; it picks its own
  underlying LLM via `METATRON_LLM_PROVIDER`.
- Hermes's own memory still works (Hermes manages its prompt), but Hermes's
  LLM choice is bypassed for these turns.
- Use this mode when you want "Hermes as a front-end for corporate Q&A." For
  agentic reasoning with tools, prefer Level 1 MCP.

## Level 3 — Access agent memory

Since memory-specific MCP tools do not exist yet, reach the Memory REST API
directly. You can wire this via a Hermes custom tool or skill.

### REST endpoints (authenticated via `mtk_` or JWT)

- `POST /api/v1/memory/create` — create a memory record
- `POST /api/v1/memory/search` — hybrid search (Qdrant + Neo4j + Redis session)
- `GET  /api/v1/memory/records` — list records
- `DELETE /api/v1/memory/records/{record_id}` — delete

Request payloads mirror `MemoryRecord` from `src/metatron/core/models.py` (content,
scope, agent_id, tags, importance_score, etc.).

### Hermes skill sketch

Create a Hermes skill (`~/.hermes/skills/metatron-memory/skill.md`) that describes
when and how to call these endpoints. Hermes's agent loop will pick it up and
issue HTTP calls. Skeleton:

```markdown
---
name: metatron-memory
description: Store and recall long-term agent memory in Metatron
---

## When to use
- User shares a fact you should remember across sessions
- User asks about something you should have recalled
- You want to consolidate a conclusion for future reference

## How
Call the Metatron memory REST API:

- Store: `POST https://<metatron>/api/v1/memory/create`
- Search: `POST https://<metatron>/api/v1/memory/search`
- Auth: header `Authorization: Bearer $METATRON_MCP_API_KEY`
- Pass `workspace_id` in the body.
```

This is a stopgap until memory-specific MCP tools are available.

## Coexistence: two memories

Hermes has its own memory (SOUL.md, MEMORY.md, USER.md, skills, FTS5 session search,
Honcho user modeling). Metatron has agent memory and document KB.

Recommended division of labor:

| Kind of knowledge | Home |
|---|---|
| Persona / agent style | Hermes (`SOUL.md`) |
| User profile / preferences | Hermes (via Honcho) |
| Procedural memory ("how to do X") | Hermes skills |
| Corporate knowledge (Confluence / Jira / Notion) | Metatron documents |
| Shared facts across agents (team decisions, product values) | Metatron memory (scope=workspace) |
| Agent-specific long-term memory ("what I learned for this user") | Metatron memory (scope=agent) |
| Session working memory | Hermes locally; optionally promoted to Metatron |

Putting the same fact in both systems is the quickest way to drift. Decide early
which system owns which fact type.

## Gotchas

### Agent identity
Metatron currently identifies an agent by API key. Multiple Hermes processes with
the same key are one agent to Metatron. If you want per-instance memory, mint one
key per Hermes instance.

### Eventual consistency on write
Memory writes that go through the (planned) assertion lifecycle pipeline do not
become searchable instantly — Linker + Reconciler + DecisionEngine run in the
background. Today the simple memory REST API returns quickly, but assertion
pipeline will add 1–5 s latency once it ships.

### Workspace isolation is strict
One Hermes instance, one workspace. Multi-tenant routing (one Hermes, many
workspaces) is not supported out-of-the-box — you would need multiple API keys
or one key with a workspace param on every call.

### `/v1/chat/completions` is not a raw LLM proxy
See Level 2 caveats.

### DNS rebinding protection on /mcp
Some MCP SDK versions enable DNS rebinding protection that rejects requests with
unexpected `Host` headers behind a reverse proxy. If you see `421 Invalid Host`,
add `proxy_set_header Host localhost;` to your proxy config for `/mcp`, or update
to a Metatron build with rebinding protection disabled in the MCP transport.

## Troubleshooting

**401 Unauthorized on `/mcp`**
Verify `METATRON_MCP_API_KEY` on the server matches the `Authorization: Bearer ...`
header in Hermes config.

**405 Not Allowed on `/mcp`**
Reverse proxy is not routing `/mcp` to the Metatron backend. Add the proxy rule above.

**`GET /mcp` returns HTML**
Same as 405 — proxy is serving the SPA. Add the proxy rule.

**Hermes does not see `metatron_*` tools**
Check that the MCP server entry is in the correct Hermes config file (`hermes config path`).
Run `hermes doctor` for diagnostics. Confirm that the MCP URL is reachable from the
Hermes host via `curl`.

**Unreachable underlying LLM in OAI mode**
In Level 2, Metatron uses its own LLM provider (`METATRON_LLM_PROVIDER`). If that
provider is unreachable, chat/completions fails. Check `make dev` logs for the
`hybrid_search_and_answer` path.

## Roadmap items that will improve this integration

Tracked in Jira (MTRNIX project):

- **MTRNIX-275** — AgentMemoryManager: auto-inject top-k memories into
  `/v1/chat/completions` system prompt.
- **MTRNIX-249** — Formalize OAI-compat endpoint with memory context injection.
- **MTRNIX-272** — Memory snapshot / restore / diff (endpoints useful for Hermes
  long-lived agent state).
- New tickets (TBD) — expose `memory_search`, `memory_store`, `memory_delete` as
  MCP tools so Hermes does not need a custom HTTP skill.
- **WS4 — Agent Registry** — partially closed by **MTRNIX-270**: backend CRUD,
  lifecycle flag (start/stop/pause) and versioned config are live at
  `/api/v1/agents/*`. Hermes instances can now register a first-class identity
  (name, model, capabilities, tools, memory bindings, budget — the last two
  are opaque JSONB today, enforcement deferred). Still open: exposing agent
  registry over MCP, 5-role RBAC (Agent Admin / Company Admin / Super Admin),
  company hierarchy.

## References

- Hermes README: https://github.com/NousResearch/hermes-agent
- Hermes MCP docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp
- Metatron MCP server code: `src/metatron/mcp/`
- Metatron memory API: `src/metatron/api/routes/memory.py`
- Metatron OAI-compat: `src/metatron/api/routes/openai_compat.py`
- OpenClaw integration (similar stack): `docs/OPENCLAW_INTEGRATION.md`
- Legacy inventory: `docs/LEGACY.md`
