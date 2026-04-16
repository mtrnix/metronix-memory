# Hermes Integration Roadmap (2026-04-16)

Implementation plan for making Metatron Core a first-class memory + knowledge
backend for the Hermes Agent (NousResearch). Phases ordered by value delivered
per phase.

Companion docs:
- `docs/HERMES_INTEGRATION.md` — current integration guide
- `docs/LEGACY.md` — what is being phased out
- `~/.claude-home/skills/metatron-arch-guard/SKILL.md` — product vision

## Phase 1 — Memory MCP tools + fast search profile (DONE)

**Goal:** Hermes can use Metatron memory and quick lookups out of the box, with
no custom HTTP skill.

Adds new MCP tools alongside the existing five (`metatron_search`, `_get`,
`_store`, `_sync`, `_status`):

- `metatron_memory_search` — wraps `POST /api/v1/memory/search`
- `metatron_memory_store` — wraps `POST /api/v1/memory/create`
- `metatron_memory_delete` — wraps `DELETE /api/v1/memory/records/{id}`
- `metatron_search_fast` — lightweight retrieval profile: dense + metadata only,
  no reranker, no LLM expansion, no HyDE; target latency 300-800 ms

Plus: smoke test against a real Hermes setup, update `docs/HERMES_INTEGRATION.md`
with concrete routing patterns.

**Status:** Done (MTRNIX-303 merged 2026-04-16). PR #79.

What landed: four new MCP tools (`metatron_memory_search`, `metatron_memory_store`,
`metatron_memory_delete`, `metatron_search_fast`) plus `fast_search()` in
`retrieval/search.py`; `MemoryService` relocated from `agent/memory_service.py` (L4)
to `memory/service.py` (L3) with a backward-compat shim at the old path;
`docs/HERMES_INTEGRATION.md` updated with the 9-tool table and a Routing patterns section.

## Phase 2 — Memory context injection in /v1/chat/completions

**Goal:** Level 2 (OAI-compat proxy) becomes useful — agent memory automatically
prepended to system prompt, without explicit tool calls from the agent.

- Build `AgentMemoryManager` (L4 facade) with `get_context(agent_id, query, top_k=5)`.
- Wire into `/v1/chat/completions`: extract `agent_id` from API key, fetch top-K
  memories, prepend as system context.
- Feature flag `METATRON_MEMORY_INJECTION_ENABLED`.
- Verify search eval does not regress.

Existing Jira tickets:
- **MTRNIX-275** AgentMemoryManager — backbone of this phase.
- **MTRNIX-249** OAI-compat — needs reformulation. Today the endpoint already
  works; the actual remaining work is "wire memory injection in." Should be
  renamed and linked to MTRNIX-275 (or merged).

## Phase 3 — Agent Registry MVP

**Goal:** Hermes instances become first-class agents with their own identity.
Different Hermes processes with different keys see different memory.

- Table `agents` (id, workspace_id, name, owner_user_id, model_config JSONB,
  allowed_scopes, created_at).
- CRUD API `/api/v1/agents/*` (admin only).
- Map API key → `agent_id` (new field on `api_keys` table).
- Memory records: `agent_id` first-class field. Decide nullable-or-required for
  legacy rows.
- Memory MCP tools (Phase 1) read `agent_id` from key, not from a tool argument.

UI for agent management (create, view, rotate keys) is deferred to WS3/WS5.

Existing Jira ticket:
- **MTRNIX-270** Agent Registry backend — fits this phase.

## Phase 4 — Snapshot / restore / reset

**Goal:** Long-lived agent memory can be backed up, rolled back, diffed. This is
a real differentiator vs Mem0 / Zep / LangChain Memory.

- Export format: JSONL + gzip + SHA-256 manifest.
- Endpoints: `POST /agents/{id}/snapshots`, `GET /agents/{id}/snapshots`,
  `POST /snapshots/{id}/restore`, `POST /agents/{id}/reset`,
  `GET /snapshots/diff?from=A&to=B`.
- CLI `python -m metatron.scripts.snapshot --agent ... --out ...`.

Existing Jira ticket:
- **MTRNIX-272** Memory snapshot / restore / diff.

## Phase 5 — Legacy cleanup

**Goal:** Reduce maintenance surface, align code base with the agent-centric
direction. Note: OpenWebUI bundled mode and `skills/` are explicitly NOT in
scope here — see `docs/LEGACY.md`.

- Remove `api/routes/finops.py` (or move to Control Center).
- Remove `api/routes/chat.py` + `agent/sessions.py` (after verifying metatronui-kb
  has no dependency).
- Extract `channels/` into an optional plugin package (`metatron-channels-plugin`).
- Remove migration `010_user_platform_mappings` if channels are extracted.

Each item lands as its own PR. No need for a single big cleanup commit.

## Phase 6 — Assertion lifecycle layer

**Goal:** Add the semantic curation layer on top of WS1 (the "MetatronMemory"
concept): assertions as first-class entities with status (CANDIDATE / ACTIVE /
SUPERSEDED / ARCHIVED), supersession + contradiction detection, review queue,
event sourcing, dialogue write-back.

This is research-uplift, not pure engineering. Only start after Phase 1-3 are
solid. Detailed design TBD; see `docs/HERMES_INTEGRATION.md` and prior
discussions for the conceptual model.

Sub-phases (rough):
- 6a — Data model + minimal pipeline (Linker, Reconciler, FreshnessMonitor,
  Curator), simple LLM DecisionEngine, REST + UI.
- 6b — Production-quality features: SupersessionDetector, ContradictionDetector,
  dialogue write-back with proper LLM claim extraction, temporal extraction,
  retrieval mixing.
- 6c — Agent-grade: agentic DecisionEngine with tools, memory consolidation
  loop, memory-type taxonomy, working memory layer.

## Decisions to settle as we go

1. **MTRNIX-249** — reformulate or close? Preferred: rename to "memory injection
   in /v1/chat/completions" and link to MTRNIX-275 as one epic.
2. **`agent_id` nullable or required** on memory records during Phase 3 migration?
3. **Channels extraction (Phase 5)** — now or after CC backend lands?
4. **Phase 1 PR size** — one combined PR or one per tool? Probably one combined
   "Hermes integration MVP" PR for review ergonomics.
