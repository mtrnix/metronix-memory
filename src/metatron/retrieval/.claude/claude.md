# Retrieval

## Overview
L2 — the full search pipeline from raw query to LLM answer with sources.
Entry point: `hybrid_search_and_answer()` in `search.py`. Fully async pipeline.

## Pipeline (current)
```
Query → [HyDE (optional, short/vague queries)] → expansion → classify(profile) → weight_preset
     → recall_dense + recall_exact + recall_metadata + recall_graph  (parallel via asyncio.gather)
     → merge_channels → compute_signal_score(6 weighted signals, normalized [0,1])
     → confidence filter (min_signal_score, default disabled)
     → top-35 pool → cross-encoder rerank (bge-reranker-v2-m3)
     → compute_final_score(blend: 30% signal + 70% reranker)
     → _prepend_root_context (fetch root chunks for child results)
     → _collect_frags(dict) → _mark_evidence_role(PRIMARY/SUPPORTING)
     → _build_ctx(grouped markdown) → LLM(evidence rules) → _append_sources → answer

Sparse search uses SPLADE learned representations (SPLADE_ENABLED=true, default ON).
Falls back to BM25 when SPLADE_ENABLED=false.
HyDE generates hypothetical document for short queries (HYDE_ENABLED=false, default OFF).
Adaptive RRF adjusts rrf_k based on dense/sparse overlap (ADAPTIVE_RRF_ENABLED=false, default OFF).
Transitive alias resolution: recall_graph resolves aliases via 1..3 hop BFS over ALIAS edges.
```

## Files

### `search.py`
Main pipeline — `async def hybrid_search_and_answer()`.
Orchestrates: language detection → translation → [HyDE] → query expansion → classification →
recall channels (parallel via asyncio.gather) → scoring → reranking → fragment collection →
evidence roles → LLM.

Key functions:
- `_run_recall_channels_async(ctx)` — parallel dispatch of 4 recall channels via `asyncio.gather`
- `_prepend_root_context()` — fetch root chunks for child results, prepend as context
- `_collect_frags()` — extract text, deduplicate, respect `_MAX_TOTAL`/`_MAX_FRAG`
- `_mark_evidence_role()` — assigns PRIMARY/SUPPORTING based on query profile
- `_build_ctx()` — assembles grouped markdown context for LLM
- `_append_sources()` — citation formatting (max 5 sources)

### `channels.py`
4 independent recall channels (sync + async variants) + merge logic:
- `recall_dense(ctx)` / `recall_dense_async(ctx)` — RRF hybrid search (dense + SPLADE/BM25 sparse via Qdrant). Supports HyDE embedding path and adaptive RRF.
- `recall_exact(ctx)` / `recall_exact_async(ctx)` — Jira key lookup + title entity search
- `recall_metadata(ctx)` / `recall_metadata_async(ctx)` — date filters, person/assignee, activity status
- `recall_graph(ctx)` / `recall_graph_async(ctx)` — entity graph traversal (BFS hop expansion via Neo4j) with transitive alias resolution (1..3 hop BFS over ALIAS edges)
- `merge_channels()` — merges results, preserves all channel scores
- `_cached_get_graph_entities()` — LRU cache (maxsize=128) for graph entity lookups
- `on_sync_completed()` — event handler clearing graph entity LRU cache

Types: `ScoredResult`, `MergedResult`, `RecallContext` (includes `hyde_embedding`
and `freshness_filter` fields).

**Freshness filter pushdown (MTRNIX-313, Phase B).** When
`METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED=true`, `search.py` builds a
Qdrant `Filter` excluding `status IN ('archived','superseded')` and passes it
on `RecallContext.freshness_filter`. Each channel combines it with
`access_filter` via `_combine_filters()` before calling the Qdrant store, so
ARCHIVED/SUPERSEDED chunks are filtered server-side without a PG round-trip.
Default off → `freshness_filter` is `None` and the code path is byte-identical
to pre-Phase-B (no extra branch, same `filter_conditions` argument sent to
Qdrant). `_combine_filters` merges `must` / `must_not` / `should` lists.

### `scoring.py`
Multi-signal scoring formula:
- `compute_signal_score(merged_result, ...)` — weighted signals (dense, graph, metadata, recency, balance, freshness), normalized to [0,1] by dividing by sum of ALL active weights
- `compute_final_score(signal_score, rerank_score, blend_weight)` — blend formula
- `source_balance(source_type, type_counts, total)` — smooth gradient (linear decay from 1.0 to 0.0 at threshold)
- `recency_score(date_str)` — time decay
- `normalize_scores(scores)` — min-max normalization for cross-encoder output

**Freshness signal (MTRNIX-313, Phase B).** `compute_signal_score` accepts an
optional `freshness` score (the `raw_documents.freshness_score` for the
document that produced the candidate; default 1.0 when unknown) weighted by
`freshness_weight` (env `METATRON_FRESHNESS_WEIGHT`, default 0.0). With the
default weight, both the numerator term and the denominator sum contribution
are zero — the formula is numerically identical to Phase A.

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
When `ADAPTIVE_RRF_ENABLED=true`, rrf_k adjusts between `RRF_K_LOW` and `RRF_K_HIGH`
based on dense/sparse overlap ratio.

### `context.py`
`_build_ctx(query, lang, frags, g_ents, g_rels, g_docs) -> str`
Assembles LLM context from fragments + graph data, grouped by evidence role.

### `prompts.py`
System prompts with atomic evidence rules for LLM.

### `fallback.py`
Graceful retrieval — `_safe_call` pattern. If a retrieval component fails (graph down,
Qdrant timeout), the retriever skips that signal and continues with available data.

### `graph_enrichment.py`
Graph-based enrichment for search results.

### Other files
- `alias_registry.py` — file-based person alias store for entity resolution
- `aliases.py` — hardcoded `NAME_ALIASES` + transitive alias resolution helpers
- `routing.py` — query type heuristics (jira, team workflow)
- `entity_resolver.py`, `entity_helpers.py` — entity extraction and resolution; includes `create_alias_relationship()` for bidirectional ALIAS edges in Neo4j

## Key Patterns
- **Fully async** — `hybrid_search_and_answer()` is `async def`; recall channels dispatched via `asyncio.gather`
- **Parallel recall** — 4 async channels run concurrently via `asyncio.gather`
- **Score isolation** — scores stored in `score_map: dict[str, float]`, not in memory dicts
- **Graceful degradation** — graph/reranker failures are caught; search continues
- **LRU cache** — graph entity lookups cached (maxsize=128)
- **Configurable weights** — all scoring weights overridable via env vars or query profiles
- **Lazy reranker** — model loaded on first call, not at import time

## Dependencies
- **Depends on**: `core.config`, `core.models`, `storage.qdrant`, `storage.graph_ops`, `storage.pg_connection`, `llm`, `ingestion.processors.dates`, `observability.metrics`
- **Depended on by**: `api.routes.chat`, `api.routes.benchmarker`
