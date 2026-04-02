# Retrieval

## Overview
L2 — the full search pipeline from raw query to LLM answer with sources.
Entry point: `hybrid_search_and_answer()` in `search.py`. Currently sync
(TODO: async migration), runs via `asyncio.to_thread()` from API layer.

## Pipeline (current)
```
Query → expansion → classify(profile) → weight_preset
     → recall_dense + recall_exact + recall_metadata + recall_graph  (parallel ThreadPoolExecutor)
     → merge_channels → compute_signal_score(6 weighted signals, normalized [0,1])
     → confidence filter (min_signal_score, default disabled)
     → top-35 pool → cross-encoder rerank (bge-reranker-v2-m3)
     → compute_final_score(blend: 30% signal + 70% reranker)
     → _collect_frags(dict) → _mark_evidence_role(PRIMARY/SUPPORTING)
     → _build_ctx(grouped markdown) → LLM(evidence rules) → _append_sources → answer
```

## Files

### `search.py`
Main pipeline — `hybrid_search_and_answer()`.
Orchestrates: language detection → translation → query expansion → classification →
recall channels (parallel) → scoring → reranking → fragment collection → evidence roles → LLM.

Key functions:
- `_run_recall_channels(ctx)` — parallel dispatch of 4 recall channels via `ThreadPoolExecutor`
- `_collect_frags()` — extract text, deduplicate, respect `_MAX_TOTAL`/`_MAX_FRAG`
- `_mark_evidence_role()` — assigns PRIMARY/SUPPORTING based on query profile
- `_build_ctx()` — assembles grouped markdown context for LLM
- `_append_sources()` — citation formatting (max 5 sources)

### `channels.py`
4 independent recall channels + merge logic:
- `recall_dense(ctx)` — RRF hybrid search (dense + sparse vectors via Qdrant)
- `recall_exact(ctx)` — Jira key lookup + title entity search
- `recall_metadata(ctx)` — date filters, person/assignee, activity status
- `recall_graph(ctx)` — entity graph traversal (BFS hop expansion via Neo4j)
- `merge_channels()` — merges results, preserves all channel scores
- `_cached_get_graph_entities()` — LRU cache (maxsize=128) for graph entity lookups

Types: `ScoredResult`, `MergedResult`, `RecallContext`

### `scoring.py`
Multi-signal scoring formula:
- `compute_signal_score(merged_result, ...)` — 5 weighted signals (dense, graph, metadata, recency, balance), normalized to [0,1] by dividing by sum of ALL weights
- `compute_final_score(signal_score, rerank_score, blend_weight)` — blend formula
- `source_balance(source_type, type_counts, total)` — smooth gradient (linear decay from 1.0 to 0.0 at threshold)
- `recency_score(date_str)` — time decay
- `normalize_scores(scores)` — min-max normalization for cross-encoder output

### `query_classifier.py`
Hybrid rule+LLM query classifier:
- Rule gate: regex patterns for Jira keys, dates, files, relationships
- LLM fallback: DeepSeek classification with confidence threshold
- 6 profiles: execution, documentation, user_file, relationship, temporal, mixed
- `QUERY_PROFILE_WEIGHTS` — per-profile weight overrides for scoring formula

### `reranker.py`
Cross-encoder reranker — `BAAI/bge-reranker-v2-m3`.
Lazy singleton (loaded on first use). `rerank(query, results, top_k)`.
Falls back gracefully if model unavailable.

### `query_expansion.py`
`expand_query(query, settings) -> str` — LLM-based query expansion.
Disabled when `QUERY_EXPANSION_ENABLED=False`. Returns original query on failure.

### `token_budget.py`
`select_fragments_within_budget(frags, max_chars) -> list[str]`
`truncate_graph_context(g_ents, g_rels, g_docs, max_tokens)` — priority: Person entities first

### `hybrid.py`
`HybridSearcher` — wraps dense + sparse search with RRF fusion.
RRF formula: `score = Σ 1/(rrf_k + rank)` where `rrf_k=60`.

### `context.py`
`_build_ctx(query, lang, frags, g_ents, g_rels, g_docs) -> str`
Assembles LLM context from fragments + graph data, grouped by evidence role.

### `prompts.py`
System prompts with atomic evidence rules for LLM.

### Other files
- `alias_registry.py` — person alias store for entity resolution
- `routing.py` — query type heuristics (jira, team workflow)
- `entity_resolver.py`, `entity_helpers.py` — entity extraction and resolution

## Key Patterns
- **Sync-first with thread offload** — `hybrid_search_and_answer()` is sync; called via `asyncio.to_thread()`
- **Parallel recall** — 4 channels run in ThreadPoolExecutor (max_workers=4)
- **Score isolation** — scores stored in `score_map: dict[str, float]`, not in memory dicts
- **Graceful degradation** — graph/reranker failures are caught; search continues
- **LRU cache** — graph entity lookups cached (maxsize=128)
- **Configurable weights** — all scoring weights overridable via env vars or query profiles
- **Lazy reranker** — model loaded on first call, not at import time

## Dependencies
- **Depends on**: `core.config`, `core.models`, `storage.qdrant`, `storage.graph_ops`, `storage.pg_connection`, `llm`, `ingestion.processors.dates`, `observability.metrics`
- **Depended on by**: `api.routes.chat`, `api.routes.benchmarker`
