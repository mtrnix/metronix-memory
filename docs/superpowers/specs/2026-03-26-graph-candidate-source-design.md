# Promote Graph from Context-Enrichment to Candidate Source

## Goal

Refactor the graph's role in the retrieval pipeline: make `recall_graph` a true
candidate source (with hop expansion and rich seed entities), and reduce step 8
to a metadata-only context builder that no longer injects document chunks.

## Problem

Currently graph participates in two places with overlapping responsibilities:

1. **`recall_graph` channel** — basic: NER on query text → doc_labels → chunks
   into rerank pool. Uses only `get_graph_entities([query_text])`, ignoring
   all other extracted signals (Jira keys, person names, title entities).

2. **Step 8 graph enrichment** — after reranker: extracts entities from top
   results, finds related documents, and adds extra chunks **directly into the
   LLM prompt**, bypassing reranking entirely.

This means graph-derived documents skip quality filtering (reranking), and the
graph recall channel underutilizes available entity signals.

## Architecture

### Current Pipeline
```
4 channels → merge → diversify → rerank → graph enrichment (docs + metadata) → token budget → LLM
```

### New Pipeline
```
4 channels (enhanced recall_graph) → merge → diversify → rerank → graph context builder (metadata only) → token budget → LLM
```

Changes:
1. **`recall_graph` channel** — enhanced: collects seed entities from 4 sources
   in RecallContext + hop expansion via graph relationships
2. **Step 8** — reduced: only builds entity/relationship metadata for LLM
   context, no longer fetches or injects document chunks
3. **Config** — new `RECALL_GRAPH_MAX_DEPTH` for hop expansion depth

## Enhanced `recall_graph` Channel

### Seed Entity Collection

Instead of only `get_graph_entities([query_text])`, the channel collects seed
entities from all available signals in RecallContext:

| Source | Example | Already extracted by |
|--------|---------|---------------------|
| Jira keys | `MTRNIX-104` | `_JIRA_KEY_RE` regex |
| Title entities | `Project Aurora`, `AMD` | `extract_title_entities()` |
| Person names | `Иванов Иван Иванович` | `_PERSON_RU/_EN` + AliasRegistry |
| Graph entity match | entities matching query text | `get_graph_entities()` |

No new extraction logic — reuses what `_build_recall_context()` already provides.

### Hop Expansion

After collecting seed entities, the channel expands via graph relationships
using an iterative BFS loop inside `recall_graph` (not relying on
`get_graph_relationships`'s `max_depth` parameter, which does not implement
multi-hop traversal — it only fetches direct edges).

Algorithm (iterative, up to `recall_graph_max_depth` rounds):

1. Get direct doc_labels for seed entities via `get_doc_labels_by_entities(seeds)`
2. **For each hop** (1..max_depth):
   a. Get relationships for current frontier via `get_graph_relationships(frontier, max_depth=1)`
   b. Extract relationship endpoint names (source/target) as new entities
   c. Remove already-seen entities → this is the new frontier
   d. Get doc_labels for new frontier via `get_doc_labels_by_entities(frontier)`
   e. Add to all_labels
   f. If frontier is empty, stop early
3. Deduplicate all doc_labels
4. Fetch chunks from Qdrant via `search_by_doc_labels()`

Depth controlled by `recall_graph_max_depth` config (default 2).

Note: `get_graph_entities([query_text])` rarely matches short queries because
it checks exact `raw_text` equality. The primary value comes from the other
three seed sources (Jira keys, title entities, person names). Person names from
`detected_person` depend on graph Entity nodes having matching canonical names
from the AliasRegistry.

### Flow

```python
recall_graph(ctx):
    # 1. Collect seed entity names from RecallContext
    seeds: set[str] = set()
    seeds.update(ctx.extracted_jira_keys)
    seeds.update(ctx.extracted_title_entities)
    seeds.update(ctx.detected_person)

    # 2. Graph entity match on query (existing behavior)
    query = ctx.translated_query or ctx.original_query
    graph_ents = get_graph_entities([query], workspace_id=ctx.workspace_id)
    seeds.update(e["name"] for e in graph_ents if "name" in e)

    if not seeds:
        return []

    # 3. Get direct doc_labels for seeds
    direct = get_doc_labels_by_entities(list(seeds), workspace_id=ctx.workspace_id)
    all_labels = {r["doc_label"] for r in direct if "doc_label" in r}

    # 4. Iterative hop expansion via relationships (BFS)
    # NOTE: get_graph_relationships accepts max_depth but does NOT do multi-hop
    # internally (depth var computed but unused in Cypher). We iterate ourselves.
    # TODO: fix misleading docstring in graph_ops.get_graph_relationships
    max_depth = ctx.settings.recall_graph_max_depth if ctx.settings else 2
    seen_entities = set(seeds)
    frontier = set(seeds)
    MAX_FRONTIER = 50  # cap to prevent explosion on highly-connected entities
    for _hop in range(max_depth):
        if not frontier:
            break
        rels = get_graph_relationships(list(frontier)[:MAX_FRONTIER],
                                       workspace_id=ctx.workspace_id, max_depth=1)
        neighbor_names = {r["source"] for r in rels} | {r["target"] for r in rels}
        frontier = neighbor_names - seen_entities  # only new entities
        seen_entities.update(frontier)
        if frontier:
            expanded = get_doc_labels_by_entities(list(frontier)[:MAX_FRONTIER],
                                                  workspace_id=ctx.workspace_id)
            all_labels.update(r["doc_label"] for r in expanded if "doc_label" in r)

    # 5. Fetch chunks, apply ACL, limit
    store = get_hybrid_store(ctx.workspace_id)
    hits = _post_filter_acl(
        store.search_by_doc_labels(list(all_labels), limit=limit),
        ctx.access_filter,
    )
    return [_qdrant_hit_to_scored(h) for h in hits[:limit]]
```

### Limit

`recall_top_n_graph` (default 5) remains unchanged — caps the channel output.
May need tuning upward (e.g., 10) since the channel now finds more candidates.

## Step 8: Graph Context Builder (Reduced)

### What is removed

The extra document chunk fetching (current lines ~618-628 in search.py):
- `search_by_doc_labels()` for related documents
- Appending those chunks to `frags`
- The `_REL_DOCS` constant that controlled the related document limit
- The `_CTX_EXTRA` constant (dead code — defined but never used, cleanup)
- The `get_related_documents()` fallback path (line 616) — no longer needed since
  enhanced `recall_graph` covers this case through the candidate pipeline

### Design decision: `active_only` in recall vs step 8

- **`recall_graph` channel (new)**: does NOT pass `active_only=True` — includes all
  relationships for broader candidate recall. Quality filtering happens via reranker.
- **Step 8 metadata (unchanged)**: keeps `active_only=True` — LLM context should
  only show currently-active relationships to avoid confusing the model.

### What remains

All metadata collection stays:
- `get_entities_by_doc_labels(doc_labels, workspace_id)` — entities from top results
- `get_graph_relationships(entity_names, max_depth, active_only)` — relationships
- Temporal filtering via `get_relationships_at_date()` when dates detected
- `get_doc_labels_by_entities()` — related document titles (metadata only)
- `truncate_graph_context()` — token budget for graph metadata
- Assembly of `g_ents`, `g_rels`, `g_docs` for `_build_ctx()`

### Result

Step 8 becomes read-only: it collects metadata for the LLM prompt but does not
modify the document set. All document-level decisions are made before reranking
through the 4 recall channels.

## Configuration

New parameter in `core/config.py`:

```python
recall_graph_max_depth: int = Field(2, alias="RECALL_GRAPH_MAX_DEPTH")
```

### Existing parameters (unchanged)

```python
recall_top_n_graph: int = Field(5, alias="RECALL_TOP_N_GRAPH")
```

Consider tuning `recall_top_n_graph` upward (e.g., 10) since the enhanced
channel will find more candidates. This is a tuning decision, not a code change.

## Error Handling

No changes to error handling patterns:
- `recall_graph` channel: try/except → `logger.error()`, returns `[]`
- Step 8: existing graceful degradation — Memgraph down → empty graph context
- Each graph_ops call is independently fault-tolerant

## Pipeline Trace

Existing `recall_graph_count` in pipeline_stages trace remains. No new trace
fields needed — the channel output count already captures graph contribution.

## What Does NOT Change

- Other 3 recall channels (dense, exact, metadata)
- Merge, diversify, title boost, reranker logic
- Token budget management (graph metadata budget stays at MAX_GRAPH_TOKENS=2000)
- LLM context assembly (`_build_ctx`)
- Source citation format
- ACL plugin hooks

## Key Files

- **Modify**: `src/metatron/retrieval/channels.py` — enhance `recall_graph` (add import of `get_graph_relationships` from `graph_ops`)
- **Modify**: `src/metatron/retrieval/search.py` — remove extra chunk fetching from step 8
- **Modify**: `src/metatron/core/config.py` — add `recall_graph_max_depth`
- **Tests**: `tests/unit/test_recall_channels.py` — update graph channel tests

## Acceptance Criteria

1. Graph-derived candidates go through reranking, not directly to prompt
2. Entity extraction uses all RecallContext signals (jira keys, title entities, person names, graph match)
3. 1-2 hop expansion working with configurable depth (`RECALL_GRAPH_MAX_DEPTH`)
4. Measurable improvement on graph-heavy queries in eval set
5. No regression on non-graph queries
6. Graceful degradation preserved (Memgraph down → search works without graph)
