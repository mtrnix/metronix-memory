# Legacy & Obsolete Functionality — Audit 2026-04-16

This document tracks modules, routes, env vars and design decisions in Metatron Core
that no longer fit the current product direction. It is a living reference for anyone
(human or agent) deciding whether to extend, repair or avoid a given area.

## Context: why things are legacy

Metatron Core pivoted in April 2026 from **"open-source enterprise RAG for corporate
knowledge management"** to **"open-source memory + knowledge infrastructure for
AI agents, with a commercial Control Center on top."** Three consequences of the
pivot that drive most of the items below:

1. External agent runtimes (Hermes, OpenClaw, Cursor, Claude Desktop, OpenWebUI,
   LibreChat) replace any notion of a built-in chat UI or messaging-bot layer.
2. User management, billing, observability and workflow orchestration move to
   the future Control Center repo. Core keeps a minimal user store for JWT/mapping.
3. Agent memory (WS1) is now first-class; document-centric features that don't
   integrate with agent memory are candidates for pruning or move-out.

Severity legend:
- **REMOVE** — unused or unimplementable in the new model; delete in a follow-up PR.
- **EXTRACT** — functional but outside Core's scope; move to a plugin, Control Center, or a separate repo.
- **DEPRECATE** — still in use but scheduled for replacement; do not extend, add docstring notice.
- **REFACTOR** — keep the concept, rework to fit the agent-centric model.

## Inventory

### 1. Built-in chat UI and in-memory SessionManager

**Files:** `src/metatron/api/routes/chat.py`, `src/metatron/agent/sessions.py`

**What it is:** `/api/v1/chat`, `/api/v1/chat/stream` endpoints with an in-memory per-user
conversation history (`SessionManager`), used by the old "Metatron as Telegram/Slack bot
for corporate KB" flow. `AgentRouter` also uses the SessionManager for follow-up detection.

**Why legacy:** External agent runtimes are the new primary consumer surface. They
manage their own session state, conversation memory and turn-by-turn reasoning.
A built-in chat endpoint with non-persistent in-memory sessions does not fit
multi-tenant agent workloads and duplicates what Hermes / OpenWebUI / LibreChat
do better.

**Severity:** EXTRACT (chat endpoints move to Control Center admin UI if kept)
or REMOVE (if CC UI uses MCP directly).

**Action:** Do not add new `/api/v1/chat/*` routes. Follow-up detection in
`AgentRouter` can be replaced by stateless request-message inspection.

### 2. OpenWebUI bundled sync — KEEP for now (active use)

**Files:**
- `src/metatron/api/routes/openwebui_import.py`
- `src/metatron/auth/openwebui_sync.py`
- Startup wiring in `src/metatron/api/app.py` (lifespan)
- `src/metatron/api/routes/users.py` (calls `owui_sync.sync_user_created()` on user CRUD)
- Env vars: `METATRON_OPENWEBUI_URL`, `METATRON_OPENWEBUI_METATRON_URL`
- `docker-compose.full.yml` profile `openwebui`

**What it is:** Three deployment scenarios (Home / Bundled / External) for running
Metatron together with OpenWebUI. In Bundled mode Metatron auto-registers
`admin@metatron.local` in OpenWebUI on startup, then mirrors user CRUD into OpenWebUI
so each user gets a personal API key and Direct Connection.

**Status:** **In active use as the primary chat front-end.** Despite the new
"external agents are the future" direction, OpenWebUI is today's working chat surface
for end users. Removing bundled sync would regress current production behavior.

**Severity:** **DO NOT touch yet.** Re-evaluate when:
- External agent runtimes (Hermes, LibreChat, custom MCP clients) become the primary
  consumer pattern in our deployments, AND
- A replacement chat surface is in place (Control Center UI or first-class Hermes setup),
  AND
- We can sunset OpenWebUI without breaking users.

Until then: do not extend the bundled sync logic, but do not deprecate it either.
`/v1/chat/completions` endpoint stays public and consumed by OpenWebUI today.

### 3. Multi-channel bots

**Files:**
- `src/metatron/channels/` (telegram.py, discord.py, slack.py, manager.py)
- `src/metatron/auth/user_mapping.py` (platform identity → internal User)
- `src/metatron/api/routes/users.py` — platform-mapping endpoints
- Alembic migration 010 (`user_platform_mappings` table)
- Tests `test_telegram.py`, etc.

**What it is:** First-class messaging bots for Telegram, Discord, Slack. Channels are
started from DB config at app startup, poll for messages, route through `AgentRouter`,
and send responses back. Each platform user ID is mapped to an internal user.

**Why legacy:** Channels were core when Metatron was "the bot that answers from your KB."
In the new model Hermes (or any external agent runtime) owns the channel side and
consumes Metatron as an MCP/OAI-compat service. Channels do not fit memory-infra framing.

**Severity:** EXTRACT — move to an optional plugin (`metatron-channels-plugin`) that
registers via the existing plugin system. If no users adopt the plugin, retire it.

**Action:** Do not add new channel types. Do not extend existing channel logic.
Any new messaging integration should be documented as "install Hermes (or similar),
point its channel gateway at Metatron MCP."

### 4. Skills engine — INACTIVE, RESERVED

**Files:** `src/metatron/skills/engine.py`, `src/metatron/skills/builtin/`,
`src/metatron/api/routes/skills.py`, `docs/SKILLS.md`

**What it is:** A system where Markdown documents describe how the LLM should use
tools. `SkillEngine.load_skills()`, `select_skills()`, `seed_builtins()` all raise
`NotImplementedError`. Routes exist but storage is not implemented.

**Status:** Currently inactive — engine never finished, no callers.

**Why kept:** MCP tool descriptions cover most "tell the LLM how to use a tool"
needs today, but a workspace-customizable, prompt-injectable skill catalog might
become useful later (per-workspace tool documentation, custom playbooks beyond
what MCP returns). Until that need is concrete, we leave the module alone.

**Severity:** **DO NOT remove.** Treat as reserved capability.

**Action:**
- Do not extend `skills/` without first checking whether MCP descriptions cover
  the need.
- Do not delete the module either — leave it dormant.
- If at some point we decide to revive skills, the existing scaffolding is a starting
  point. If we decide MCP is sufficient, then we delete — but only as an explicit
  product decision, not silently.

### 5. FinOps (time-savings metric)

**Files:** `src/metatron/api/routes/finops.py`

**What it is:** Endpoint that computes "reading-time saved" for corporate users
by comparing query result word count to manual-reading baseline.

**Why legacy:** A KB-era business metric. Doesn't translate to agent workloads —
agents don't read, they embed.

**Severity:** EXTRACT or REMOVE. If Control Center wants usage metrics, it can pull
from `query_traces` directly.

### 6. Benchmarker module

**Files:** `src/metatron/benchmarker/`, `src/metatron/api/routes/benchmarker.py`,
optional dependency `benchmark-qed`

**What it is:** Offline evaluation harness + query trace writer used for grid-search
scoring weights and regression monitoring.

**Why might be legacy:** Valuable as a dev tool, but not essential infra. Could live
as a separate repo or devtool package that depends on Core.

**Severity:** EXTRACT (eventual). Not urgent. Current lazy-load in `api/app.py`
(wrapped in try/except ImportError) is acceptable interim.

### 7. User CRUD routes (vs minimal store)

**Files:** `src/metatron/api/routes/users.py`, `src/metatron/auth/user_store.py`,
`src/metatron/auth/api_key_store.py`

**What it is:** Admin endpoints for user CRUD with bundled OpenWebUI sync hook.

**Why legacy (partially):** User management is Control Center's responsibility in the
new architecture. Core still needs a minimal store for JWT claims and platform mapping,
but full CRUD surface belongs in CC.

**Severity:**
- `user_store.py` and `api_key_store.py`: **keep** (JWT + API keys).
- CRUD routes: EXTRACT to Control Center.

### 8. Deprecated config vars

**File:** `src/metatron/core/config.py`

| Var | Status | Notes |
|---|---|---|
| `METATRON_OPENWEBUI_URL` | DEPRECATE | Bundled OpenWebUI sync — see item 2 |
| `METATRON_OPENWEBUI_METATRON_URL` | DEPRECATE | Same |
| `MEMGRAPH_*` aliases on `NEO4J_*` | KEEP | Backward-compat for env-var migration from Memgraph → Neo4j CE 5 (PR #65). Mark aliases as deprecated in docstring; do not remove until a major bump. |

**Action:** Add deprecation notes in Settings docstrings for `METATRON_OPENWEBUI_*`.
Mark `MEMGRAPH_*` aliases as legacy in docstring; continue to support them.

### 9. Workspace model ("KB tenant" vs "company + agents")

**Files:** `src/metatron/workspaces/manager.py`, `src/metatron/workspaces/models.py`

**What it is:** Current workspace abstraction = isolated KB partition (documents,
chunks, connectors, users per workspace).

**Why might be legacy:** PRD 2.0 separates "company" (organization tenant, has many
agents) from "agent" (per-agent memory scope). The current flat workspace model
conflates them.

**Severity:** REFACTOR (do not break). Incrementally add `agent_id` as a first-class
field on memory records; keep workspace_id isolation everywhere it already exists.

**Decision (MTRNIX-270, 2026-04-21):** agent registry backend lives in Core as a
first-class L3 module (`metatron.agents`, `/api/v1/agents/*`). `memory_records.agent_id`
stays as a soft-reference (free string, no FK) so Hermes can continue writing memory
without prior registration. Company / department / team hierarchy and governance
layers (billing, budget enforcement, memory_bindings enforcement) are deferred to
a future CC plugin and tracked separately.

### 10. RBAC 3-role vs 5-role

**Files:** `src/metatron/auth/rbac.py` (hierarchy viewer < editor < admin)

**Why might be legacy:** Target role hierarchy per PRD 2.0 is Viewer / Editor /
Agent Admin / Company Admin / Super Admin — five roles with memory-access granularity.
MTRNIX-187 (In Progress since the enterprise era) is the ticket for this work.

**Severity:** REFACTOR. Do not build new features on current 3-role model.
Decide during WS4 whether to finish MTRNIX-187 with 5 roles or close it and
open a new WS4 task.

**Interim note (MTRNIX-270):** the Agent Registry backend landed on the existing
3-role model — reads via `require_viewer`, writes and lifecycle via `require_editor`.
Agent Admin / Company Admin roles will attach cleanly without an API shape change
once the 5-role rework lands.

## What stays in Core

For clarity — the following are explicitly in-scope and NOT legacy:

- `memory/` (L3) + `agent/memory_service.py` — agent memory system (WS1). First-class
  and actively built.
- `agents/` (L3) — Agent Registry (WS4, MTRNIX-270). Core primitive for agent identity;
  governance/billing/5-role enforcement layers go to the future CC plugin.
- `mcp/` — MCP server, tools, client, adapter. The primary external-agent surface.
- `retrieval/` — search pipeline with SPLADE, reranker, query classifier, HyDE,
  graph enrichment.
- `ingestion/` — document pipeline, chunking, dedup, processors.
- `connectors/` — Confluence, Jira, Notion, GitHub, GDrive, Slack history, files.
- `storage/` — Postgres, Qdrant, Neo4j, Redis clients.
- `observability/` — health, metrics, tracer.
- `auth/` — JWT, RBAC (with refactor), dependencies, minimal user store.
- `workspaces/` — core tenant isolation (with refactor toward company+agent split).
- `core/` — config, interfaces, events, plugin manager, models.
- `core/plugin.py` + extension points — how Enterprise and CC repos extend Core.

## Roll-out plan

Legacy items should not be removed in one big PR. Suggested order:

1. **Phase A (docs only, this audit):** add legacy banners, LEGACY.md, update
   CLAUDE.md and arch-guard skill. No code change. **← done 2026-04-16**
2. **Phase B (extractions, deferred):** move `channels/` into an optional plugin
   package. Move FinOps to Control Center (or remove). Requires coordinating
   plugin install path.
3. **Phase C (chat removal, deferred):** delete `/api/v1/chat/*` and SessionManager.
   Verify metatronui-kb does not depend on them.
4. **Phase D (OpenWebUI sunset, NOT scheduled):** triggered only when external
   agents become the primary chat surface AND a replacement is in place. Until
   then, leave openwebui_sync / openwebui_import alone.
5. **Phase E (skills decision, NOT scheduled):** explicit go/no-go on `skills/`
   module — keep dormant or delete. Deferred until the question is concrete.
6. **Phase F (refactors, part of WS4):** RBAC 5-role rework. Workspace → company+agent
   split.

Each phase should land as its own PR with tests and a CHANGELOG entry.

## References

- Product vision: `~/.claude-home/skills/metatron-arch-guard/SKILL.md`
- Hermes integration: `docs/HERMES_INTEGRATION.md`
- OpenClaw integration: `docs/OPENCLAW_INTEGRATION.md`
- WS1 memory module context: `src/metatron/memory/.claude/CLAUDE.md`
- Root project rules: `CLAUDE.md`
