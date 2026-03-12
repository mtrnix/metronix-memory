
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
