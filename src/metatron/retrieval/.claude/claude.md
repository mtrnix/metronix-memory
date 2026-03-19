# Retrieval

## Overview
L2 — the full search pipeline from raw query to LLM answer with sources.
Entry point: `hybrid_search_and_answer()` in `search.py`. Currently sync
(all TODO: async migration comments), runs via `asyncio.to_thread()` from API layer.

## Files

### `search.py`
Main pipeline — `hybrid_search_and_answer()`.

**Global constants (from Settings at module import time):**
```python
_MAX_TOTAL = search_max_total_chars   # 40000
_MAX_FRAG  = search_max_fragment_chars # 8000
_POOL_MUL  = search_pool_multiplier   # 3  (pool = k * 3)
_POOL_MIN  = search_pool_min          # 15 (minimum pool size)
_GRAPH_DEPTH = 2
_JIRA_KEY_RE = r'\b([A-Z]{2,}-\d+)\b'
```

**Full pipeline in `hybrid_search_and_answer(query, workspace_id, k, ...)`:**
1. **Language detection** — `detect_response_language()`: Cyrillic detection → `"ru"` else `"en"`
2. **Cyrillic translation** — `translate_query_to_english()` via LLM if Cyrillic detected
3. **Jira key injection** — regex extracts `PROJ-123` patterns → direct `_inject_jira_key_results()`
4. **Person/activity injection** — `_ACTIVITY_KW` + `_PERSON_RU`/`_PERSON_EN` regex → entity resolution via `AliasRegistry`
5. **Title entity extraction** — `extract_title_entities()` → `_build_title_filter()` → `_search_by_title()`
6. **Schema routing** — `should_use_team_workflow_schema()` → `TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT`
7. **`search_with_date_filter()`** — pool = `max(k * _POOL_MUL, _POOL_MIN)`
   - Date range detection → separate date-filtered search merged with unfiltered
   - Jira multiplier (`_JIRA_MUL=2`) when Jira query detected
   - Falls back to plain `store.hybrid_search(query, limit=k)`
8. **`diversify_results(base, k=50)`** — de-duplicate by source, interleave by type
9. **Title boost** — `_boost_title_matches()` promotes title matches to top
10. **Reranker** — if `RERANKER_ENABLED`: `rerank(query, base, top_k=25)` via `reranker.py`
11. **`_collect_frags()`** — extract text, deduplicate by truncated hash, respect `_MAX_TOTAL`/`_MAX_FRAG`
12. **Graph enrichment** —
    - `get_entities_by_doc_labels()` or `get_graph_entities(frags, workspace_id)`
    - `get_graph_relationships()` with `max_depth=_GRAPH_DEPTH`
    - Related docs via `get_related_documents()` → extra frags via `search_by_doc_labels()`
13. **Token budget** — `select_fragments_within_budget(frags, ...)` — trims to `LLM_CONTEXT_MAX_TOKENS`
14. **LLM call** — `chat_completion()` / `chat_completion_with_retry()` with built context
15. **Source append** — `_append_sources(answer, base)` — max 5 sources

**Trace logging** (non-blocking, after answer):
```python
source_word_count = sum(len(frag.split()) for frag in frags)
store_query_trace_sync(workspace_id, rq, trace_data, total_ms)
```

### `reranker.py`
Cross-encoder reranker — `BAAI/bge-reranker-v2-m3`.
Lazy singleton (loaded on first use). `rerank(query, results, top_k=25) -> list`.
Falls back gracefully if model unavailable.

### `query_expansion.py`
`expand_query(query, settings) -> str` — LLM-based query expansion.
Disabled when `QUERY_EXPANSION_ENABLED=False`. Returns original query on failure.

### `token_budget.py`
`MAX_GRAPH_TOKENS = 2000`
`estimate_graph_tokens(g_ents, g_rels, g_docs) -> int`
`truncate_graph_context(g_ents, g_rels, g_docs, max_tokens)` — priority: Person entities first
`select_fragments_within_budget(frags, max_chars) -> list[str]`

### `alias_registry.py`
`AliasRegistry` — file-persisted person alias store at `.metatron/person_aliases.json`.
Singleton via `get_alias_registry()`. Auto-populated from Jira sync.
Maps display names / Cyrillic names to canonical identifiers for person queries.

### `aliases.py`
Hardcoded fallback alias dict — used when `alias_registry.json` doesn't exist yet.

### `routing.py`
`is_jira_query(query) -> bool` — keyword heuristics.
`should_use_team_workflow_schema(query) -> bool` — detects team/workflow questions.
`_extract_json_object(text) -> dict | None` — robust JSON extraction from LLM output.

### `hybrid.py`
`HybridSearcher` — wraps dense + sparse search with RRF fusion.
RRF formula: `score = Σ 1/(rrf_k + rank)` where `rrf_k=60`.
Weight blend: dense=0.35, sparse=0.20, tags=0.20, graph=0.15, recency=0.10.

### `scoring.py`
Multi-factor scoring post-RRF fusion: recency decay, tag overlap, title match boost.

### `entity_resolver.py`
`resolve_entity(name, workspace_id)` — resolves ambiguous entity names using alias registry
and graph lookup.

### `entity_helpers.py`
Helper functions for entity extraction from query text. Proper noun detection,
company token extraction (`_PROPER_NOUN_RE`, `_COMPANY_TOKEN_RE`, `_COMPANY_MULTI_RE`).

### `graph_enrichment.py`
`GraphEnricher` — wraps graph entity/relationship injection.
Currently has `NotImplementedError` stubs; actual graph ops are called directly in `search.py`.

### `fallback.py`
`GracefulRetriever` — wraps retrieval with `_safe_call()` pattern.
If Memgraph is down → search continues without graph enrichment.
Currently has `NotImplementedError` stubs.

### `context.py`
`_build_ctx(query, lang, frags, g_ents, g_rels, g_docs) -> str`
Assembles the LLM context string from fragments + graph data.

### `prompts.py`
System prompts:
- `HYBRID_SYSTEM_PROMPT` — standard RAG answer prompt
- `TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT` — structured JSON output for team workflow queries
- `TEAM_WORKFLOW_SCHEMA_SPEC` — JSON schema for structured output

## Key Patterns
- **Sync-first with thread offload** — `hybrid_search_and_answer()` is sync; called via `asyncio.to_thread()` from chat route
- **Graceful degradation** — graph failures are caught and logged; search returns results without graph enrichment
- **Pool multiplier** — always fetch `k * _POOL_MUL` candidates, rerank down to `k`
- **Lazy reranker** — model loaded on first call, not at import time (avoids slow startup)
- **FinOps integration** — `source_word_count` written to `query_traces.trace` JSONB after every answer

## Dependencies
- **Depends on**: `core.config`, `core.models`, `storage.qdrant` (hybrid search), `storage.graph_ops` (graph queries), `storage.pg_connection` (trace logging), `llm` (chat_completion), `ingestion.processors.dates`, `observability.metrics` (@timed)
- **Depended on by**: `api.routes.chat` (main search endpoint), `api.routes.benchmarker` (traced queries)
