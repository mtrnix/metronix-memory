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
| `METATRON_FRESHNESS_KB_ENABLED` | `false` | Enables the KB (raw_documents) freshness pipeline. End-to-end validated 2026-04-25 (PR #95 fixed a UUID/source_id bug discovered during validation). | Requires `FRESHNESS_ENABLED=true`. Run `make eval-compare` with/without to gauge drift |
| `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED` | `false` | Push-down ARCHIVED/SUPERSEDED filter into document retrieval. Validated end-to-end on a single archived doc — filtered correctly. STALE docs are deliberately NOT excluded (only ARCHIVED + SUPERSEDED); STALE rank-downgrade requires `FRESHNESS_WEIGHT > 0`. | Run `make eval-compare`; ±0.5 pp NDCG band |
| `METATRON_FRESHNESS_WEIGHT` | `0.0` | Adds a freshness signal to the scoring formula | Any value > 0 changes rankings; grid-search weights first |
| `HYDE_ENABLED` | `false` | HyDE for short/vague queries | Currently regresses eval, off by default |
| `ADAPTIVE_RRF_ENABLED` | `false` | Adaptive RRF fusion | Currently regresses eval, off by default |

## Known issues & workarounds

### Event loop flake in `scripts/run_eval.py`

Resolved in MTRNIX-323 — eval driver collapsed to a single `asyncio.run()` so the cached async Qdrant client stays bound to one loop for the entire run. Three consecutive `make eval` runs now emit zero `qdrant.async.hybrid_search.fallback` events.

### Eval dataset v1.3 — temporal queries still pinned

Resolved in MTRNIX-323; dataset bumped to v1.4. Four temporal/status queries (`exec-02`, `time-01`, `time-03`, `ru-02`) were rewritten to topic-anchored form, and two sprint-anchored queries (`time-05`, `agg-01`) were marked `stable: false` until sprint-aware retrieval lands.

### Agent Registry soft-delete semantics

Hardened in MTRNIX-323 — `POST /api/v1/agents/{id}/start|stop|pause` from `ARCHIVED` now returns 400 (`AgentInvalidStateTransitionError`); the new `POST /api/v1/agents/{id}/restore` (editor+) is the only path back, and lands in `STOPPED`. See CHANGELOG.

### Optional: OAI-compat smoke

Smoke covered by `tests/integration/api/test_openai_compat_smoke.py` (MTRNIX-323).

### Pre-existing code regressions accepted

- Recall channels refactor (~March 31) introduced a documented −6–8% on eval metrics. Accepted trade-off for cleaner architecture; will be revisited once WS1 lands end-to-end.
- `recall_dense_async` previously returned `[]` silently under heavy concurrent sync load. Fixed in PR #88 (`2026-04-23`), but older snapshots of develop may still show it.

## Known unknowns (untested surfaces)

These are areas we did **not** validate during the MTRNIX-319 gate. Treat them as "unproven" rather than "broken" — code paths exist, unit tests cover them, but no live-environment evidence yet.

| Surface | Why not tested | Risk if you flip / use it | Mitigation |
| --- | --- | --- | --- |
| Hermes as a real MCP client | Their LLM provider was rate-limited during validation | Hermes-specific argument tokenisation may garble parameters (we saw this once with `workspace_id` → `<\|"\|>MTRNIX<\|"\|>`); MCP transport itself was validated via direct Python client | Validate via Hermes once their LLM is back; transport-side fix would be theirs |
| `FRESHNESS_ENABLED=true` under sustained production load | Only ran ~15 min dry-run on 20 records | Worker SLM (DecisionEngine) latency under hundreds-per-minute QPS unknown; backoff thresholds unproven | Run a 24h soak on staging with real producer traffic before flipping in prod |
| `FRESHNESS_KB_ENABLED=true` on the full 475-doc corpus | Validated end-to-end on 1 document; bulk batch performance unknown | Qdrant `update_payload_by_doc_label` × 475 + Ollama for DecisionEngine × 475 may saturate; no failure mode observed but also no observation | Roll out staged: 50 docs → 200 → all. Watch `freshness_qdrant_sync_failed_total` and Ollama queue |
| Multi-worker reclaim in a docker-compose deploy | Logic validated via `test_reclaim_sigkill.py` (subprocess), not in a real two-container setup | Heartbeat + reclaim lock interaction across true network boundary unproven | Spin up 2 worker containers for one staging soak; watch `freshness_orphans_reclaimed_total` |
| `make eval-compare` with `KB_ENABLED=true` after corpus naturally ages | Only ran with `KB_STALE_AFTER_DAYS=0` (artificial all-stale) | Mass STALE/SUPERSEDED transitions over days/weeks may shift retrieval distribution unpredictably | Re-run eval weekly post-flip; track aggregate metric drift |
| Real-life integration patterns of the consuming team | They haven't started yet | Unknown unknowns — first day of integration is when the real bugs show up | Be available for the first week, expect to file follow-up tickets |

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
