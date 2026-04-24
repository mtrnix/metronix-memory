# Metatron Core — Rollout Notes

**Cut date:** 2026-04-24
**Baseline commit:** develop @ `65cb4f5` (post-MTRNIX-322)
**Preceded by:** MTRNIX-319 pre-prod validation gate

This note is for teams picking up Metatron Core for the first time. It covers what ships, what is known-safe, what is known-broken-but-flag-gated, and what to expect operationally.

## What you get

- **MCP server** (`/mcp`, Streamable HTTP) with 14 tools — document RAG + agent memory + review queue. Full reference: `docs/MCP_API.md`, integration guide: `docs/HERMES_INTEGRATION.md`.
- **OpenAI-compatible endpoint** (`/v1/chat/completions`) — RAG-backed completions for OpenWebUI / LibreChat / any OAI SDK.
- **REST API** (`/api/v1/*`) — raw CRUD for memory, documents, workspaces, connectors, **agents** (new — MTRNIX-270).
- **Freshness worker** (opt-in, `python -m metatron.memory.freshness`) — background lifecycle maintenance for agent memory and KB.
- **Enterprise plugin** (optional) — JWT auth, RBAC, audit log, usage metering. Loaded automatically when the package is present.

## What has been validated

Ran through MTRNIX-319 pre-prod gate:

| Area | Status | Notes |
|---|---|---|
| Search quality on live corpus | ✅ Baseline: P@10=0.14, MRR=0.63, NDCG@10=0.58 on refreshed v1.3 eval set | Honest numbers; includes known drift since March |
| Connector sync with non-ASCII content | ✅ Russian Confluence article synced end-to-end, top-1 score 1.00 on Russian query | Tested on live Confluence during validation |
| Freshness worker | ✅ Starts clean, idles correctly on empty queue, processes jobs in ~700ms through all 5 stages | Flag-gated via `METATRON_FRESHNESS_ENABLED` |
| Review-queue e2e via MCP | ✅ Reconciler flags near-duplicates, `memory_review_resolve` is atomic (PR #89) | Unicode `notes` payload round-trips byte-for-byte |
| Agent Registry CRUD + lifecycle + RBAC | ✅ 13 checks green; see "Quirks" below for UX notes | `/api/v1/agents/*` |
| Neo4j post-restart | ✅ 2448 nodes / 7827 rels healthy, Russian entities stored natively | Per-workspace scoping works |
| Status filter on memory search | ✅ Push-down filter works on Qdrant + PG + graph legs | Default `["active"]`; `["all"]` disables |
| UTF-8 across the stack | ✅ JSONB writes with Russian/em-dash/emoji round-trip cleanly | Metadata migration done locally; docker-compose default already UTF-8 |

## What ships flag-off (safe default)

These features are in the codebase but gated off. Flipping them requires explicit decision and validation.

| Flag | Default | What flipping does | Pre-flip gate |
|---|---|---|---|
| `METATRON_FRESHNESS_ENABLED` | `false` | Starts the memory freshness worker | Run worker on staging ≥15 min on empty queue first |
| `METATRON_FRESHNESS_KB_ENABLED` | `false` | Enables the KB (raw_documents) freshness pipeline | Requires `FRESHNESS_ENABLED=true`. Run `make eval-compare` with/without to gauge drift |
| `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED` | `false` | Push-down ARCHIVED/SUPERSEDED filter into document retrieval | Run `make eval-compare`; ±0.5 pp NDCG band |
| `METATRON_FRESHNESS_WEIGHT` | `0.0` | Adds a freshness signal to the scoring formula | Any value > 0 changes rankings; grid-search weights first |
| `HYDE_ENABLED` | `false` | HyDE for short/vague queries | Currently regresses eval, off by default |
| `ADAPTIVE_RRF_ENABLED` | `false` | Adaptive RRF fusion | Currently regresses eval, off by default |

## Known issues & workarounds

### Event loop flake in `scripts/run_eval.py`

Running `make eval-compare` produces 8 `qdrant.async.hybrid_search.fallback` events out of 29 queries — an async client lifecycle bug in the eval script itself (not in the product). Queries degrade to partial recall silently on those 8 items. Tracked in MTRNIX-323 (eval infra cleanup).

**Workaround:** eval numbers are a ±0.02 P@K noise band. Treat metrics as directional.

### Eval dataset v1.3 — temporal queries still pinned

The dataset we shipped today fixes **11 Confluence doc_label IDs** that had moved after a workspace reorg (MTRNIX-319 §5). Remaining caveat: queries like `time-01 "What tickets were created this month?"` or `exec-02 "What tasks are currently in progress?"` still reference specific Jira tickets that were "in progress last sprint" — those tickets transitioned to Done, so these queries will always miss now. Tracked in MTRNIX-323 for refresh.

**Workaround:** focus on the non-temporal categories (doc, rel, mix, ru, typo) for meaningful quality signal.

### Agent Registry soft-delete semantics

`DELETE /api/v1/agents/{id}` is a soft-delete (`status=archived`) — `GET /{id}` after DELETE returns 200 with the archived record (by design — admin visibility). More surprisingly, `POST /{id}/start` on an archived agent **transitions it back to `active`** — effectively an un-delete via lifecycle. Not technically a bug (the spec says lifecycle is a simple status flip), but UX-non-obvious.

**Workaround:** if you want a truly destructive delete, use direct DB access or wait for the explicit `force_delete` API. If you want "undelete", `POST /{id}/start` is the path — document this in your client code.

### Pre-existing code regressions accepted

- Recall channels refactor (~March 31) introduced a documented −6–8% on eval metrics. Accepted trade-off for cleaner architecture; will be revisited once WS1 lands end-to-end.
- `recall_dense_async` previously returned `[]` silently under heavy concurrent sync load. Fixed in PR #88 (`2026-04-23`), but older snapshots of develop may still show it.

## Operational setup

### Required services

All on default ports unless noted:

- PostgreSQL 16+ (UTF-8 encoding required for JSONB freshness payloads — docker-compose `postgres:16-alpine` defaults to this)
- Qdrant v1.16+
- Neo4j CE v5
- Redis (for session cache + freshness queue)
- Ollama OR any OpenAI-compatible LLM endpoint

### Auth surface

- **MCP endpoint** (`/mcp`) — single bearer token via `METATRON_MCP_API_KEY`
- **REST API + OAI-compat** — JWT via `/api/v1/auth/login` (email + password) OR personal API keys `mtk_...`
- **Enterprise plugin** forces `AUTH_ENABLED=true` when present

### First-run checklist

1. Set `.env` per `docs/GETTING_STARTED.md`
2. `make docker-up` for PG / Qdrant / Neo4j / Redis
3. `make migrate` (Alembic auto-runs on app startup too)
4. `python -m metatron.app` — API + channels (Telegram/Slack/Discord if configured)
5. Optional, in a separate terminal: `python -m metatron.memory.freshness` — only after setting `METATRON_FRESHNESS_ENABLED=true` in `.env`

### Smoke test recipe

After first run, validate with:

```bash
# 1. Health
curl -sS http://localhost:8000/health

# 2. JWT login (enterprise plugin)
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<admin@your.domain>","password":"<pw>"}' | jq -r .token)

# 3. Store a memory
curl -sS -X POST http://localhost:8000/api/v1/memory/records \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id":"smoke","content":"test memory","scope":"per_agent"}'

# 4. Search it back
curl -sS -X POST http://localhost:8000/api/v1/memory/search \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id":"smoke","query":"test memory"}'

# 5. Create an agent
curl -sS -X POST http://localhost:8000/api/v1/agents \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"smoke","model":"claude-sonnet-4-5"}'
```

For MCP validation, use a real MCP client (Claude Desktop / Cursor / Hermes with a working LLM) and call `metatron_search_fast`.

## Roadmap items filed as follow-ups

- **MTRNIX-323** — pre-rollout follow-ups bundle (eval infra flake, dataset refresh, Agent Registry UX decision, optional OAI-compat smoke)
- **MTRNIX-322** — Memory freshness Qdrant sync (already merged — `2026-04-24`)
- **MTRNIX-316** — Freshness queue reliability (pre-prod gate for flipping `FRESHNESS_ENABLED=true` in a production environment)

## References

- Architecture — `docs/ARCHITECTURE.md`
- MCP reference — `docs/MCP_API.md`
- Hermes integration — `docs/HERMES_INTEGRATION.md`
- Memory MCP follow-ups — `docs/MEMORY_MCP_FOLLOWUPS.md`
- Per-module rules — `src/metatron/*/.claude/CLAUDE.md`
