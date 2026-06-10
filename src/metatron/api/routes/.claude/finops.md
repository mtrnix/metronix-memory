
# FinOps — Time Savings API

## Overview
Endpoint that calculates how much time Metatron saves users compared to manually reading source documents.

## Endpoint
`GET /api/v1/finops/time-savings?workspace_id={id}&days={30}`

## Time Savings Formula (per query)
```
manual_reading_time = (source_word_count / 150 WPM) × 1.5 search overhead
metatron_time = total_ms / 60_000 (ms → minutes)
time_saved = max(0, manual_reading_time - metatron_time)
```
- 150 WPM = average reading speed for technical documentation
- 1.5× = multiplier for time spent finding the right document before reading
- time_saved is floored at 0 (Metatron can't "lose" time for the user)

## Data Source
- Table: `query_traces` (PostgreSQL)
- Key fields: `total_ms` (Float), `trace` (JSONB containing `source_word_count`)
- `source_word_count` added in trace JSONB — no migration needed
- Legacy traces (before this feature) have no `source_word_count` → defaults to 0

## Where source_word_count is recorded
`src/metatron/retrieval/search.py` → `hybrid_search_and_answer()` → line ~686:
```python
source_word_count = sum(len(frag.split()) for frag in frags) if frags else 0
```
`frags` = text fragments sent to LLM as context. Word count = sum of words across all fragments.

## Response Schema
```json
{
  "period_days": 30,
  "total_queries": 142,
  "total_time_saved_minutes": 847.3,
  "avg_time_saved_per_query_minutes": 5.97,
  "avg_response_time_ms": 2340,
  "total_source_words_processed": 1250000,
  "daily_breakdown": [
    {"date": "2026-03-01", "queries": 12, "time_saved_minutes": 67.2}
  ]
}
```
Empty days in the period are filled with zeros.

## Implementation Notes
- `_fetch_time_savings()` is sync — runs via `asyncio.to_thread()` to avoid blocking event loop
- ORM rows converted to dicts **inside** session scope to avoid DetachedInstanceError on JSONB access
- Uses `get_session()` from `storage/pg_connection.py` (same pattern as dashboard_queries.py)

## Related Files
- Backend: `src/metatron/api/routes/finops.py` (endpoint)
- Backend: `src/metatron/retrieval/search.py` (trace recording)
- Frontend: `metatronui/src/api/finops.ts` (API client)
- Frontend: `metatronui/src/components/finops/FinOpsPage.tsx` (widget)

## Future: Cost Savings (MTRNIX-169, separate task)
Will add `GET /api/v1/finops/cost-savings` — compares OpenAI API cost vs Metatron infrastructure cost per document. Different formula, different endpoint, same FinOps page.

---

# FinOps — Active Users API (MTRNIX-341)

## Overview
Backs the "Unique Users" and "Avg Queries/User" dashboard cards. Counts distinct
authenticated principals who completed a RAG answer in the window, plus total queries
from the same filtered slice.

## Endpoint
`GET /api/v1/finops/active-users?workspace_id={id}&days={30}`
- `days`: 1..365, default 30 (same contract as `/time-savings`).

## Response Schema
```json
{
  "period_days": 30,
  "active_users": 42,
  "period_queries": 1337
}
```
- `active_users` — `COUNT(DISTINCT user_id)` over the filtered slice.
- `period_queries` — `COUNT(*)` over the SAME slice; frontend computes
  `Avg Queries/User = period_queries / active_users`. Do NOT divide
  `/time-savings.total_queries` (different slice — includes MCP/other) by `active_users`.

## Data Source
- Table: `llm_generation_log` (PostgreSQL, migration 022, MTRNIX-336) — NOT `query_traces`.
- Filter: `source IN ('oai_compat', 'rest')`, `call_site = 'rag_answer'`, `user_id IS NOT NULL`,
  `created_at >= now() - days`.
- `user_id` here comes from the authenticated `TelemetryContext` (trustworthy), unlike
  `query_traces.trace->>'user_id'` which defaults to the literal `"user"` for MCP calls.

## Why these filters
- `source IN ('oai_compat','rest')` — excludes MCP (no per-user identity), ingestion,
  freshness, benchmark (system traffic, no user_id).
- `call_site='rag_answer'` — only the synthesis LLM call counts as "used RAG"; users whose
  pipeline failed earlier (resolve/translate/expand/classify) are not counted.
- `user_id IS NOT NULL` — redundant for COUNT(DISTINCT) but REQUIRED for COUNT(*) so anonymous
  rows don't inflate the avg numerator.

## Known limitations
- **No workspace-vs-JWT check.** `workspace_id` is a query param; any authenticated caller can
  read any workspace's counts. Matches the existing `/time-savings` and `/cost-savings` posture.
  A workspace-scoped JWT check across all FinOps endpoints is tracked separately.
- **Opt-out is write-time only.** Workspaces with `llm_telemetry_opt_out=true` have no rows and
  return 0/0 — but only if opted out from the start. Toggling opt-out ON after rows accumulate
  does not retroactively hide them (no JOIN to `workspaces`).
- **"Users" = authenticated principals, not humans.** An external agent (Hermes) using one
  service-account API key over OpenAI-compat counts as one user.

## Implementation Notes
- `_fetch_active_users()` returns `ActiveUsersCounts` NamedTuple; sync, runs via `asyncio.to_thread()`.
- `_RAG_ANSWER_CALL_SITE` / `_USER_FACING_SOURCES` module constants — coupled by literal value to
  `retrieval/search.py` (which passes `call_site="rag_answer"`); search.py is L2 and cannot import
  upward, so a rename there must be mirrored here manually.
- Graceful degradation: DB error → `(0, 0)` + structlog warning `finops.active_users.db_error`.

## Related Files
- Backend: `src/metatron/api/routes/finops.py` (`_fetch_active_users`, `get_active_users`)
- Backend: `src/metatron/storage/pg_models.py` (`LLMGenerationLogRow`)
- Tests: `tests/unit/test_finops_active_users.py`
