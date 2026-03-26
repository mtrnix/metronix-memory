# Graph Candidate Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance `recall_graph` to use all RecallContext signals as seed entities with iterative BFS hop expansion, and reduce step 8 to metadata-only context (no document chunk injection).

**Architecture:** The graph channel collects seeds from 4 sources (Jira keys, title entities, person names, graph entity match), then iteratively expands via `get_graph_relationships` (1 hop per call, up to `recall_graph_max_depth` iterations). Step 8 keeps its entity/relationship metadata collection for LLM context but stops injecting extra document chunks into the fragment list.

**Tech Stack:** Python 3.12, Memgraph (via `graph_ops`), Qdrant (via `get_hybrid_store`), pydantic-settings

**Spec:** `docs/superpowers/specs/2026-03-26-graph-candidate-source-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/metatron/core/config.py:115` | Add `recall_graph_max_depth` setting |
| Modify | `src/metatron/retrieval/channels.py:13,205-234` | Enhance `recall_graph` with seed collection + BFS hop expansion |
| Modify | `src/metatron/retrieval/search.py:38-48,617-628` | Remove chunk injection from step 8, remove dead code |
| Modify | `tests/unit/test_recall_channels.py:262-296` | Rewrite graph channel tests for new behavior |
| Modify | `tests/unit/test_search_trace_extended.py` | Remove `get_related_documents` patch |
| Modify | `tests/unit/test_benchmarker_search_trace.py` | Remove `get_related_documents` patch |

---

### Task 1: Add `recall_graph_max_depth` config parameter

**Files:**
- Modify: `src/metatron/core/config.py:115`
- Test: `tests/unit/test_recall_channels.py` (verified in Task 2)

- [ ] **Step 1: Add the config field**

In `src/metatron/core/config.py`, after line 115 (`recall_top_n_graph`), add:

```python
    recall_graph_max_depth: int = Field(2, alias="RECALL_GRAPH_MAX_DEPTH")
```

- [ ] **Step 2: Verify config loads**

Run: `python -c "from metatron.core.config import Settings; s = Settings(); print(s.recall_graph_max_depth)"`
Expected: `2`

- [ ] **Step 3: Commit**

```bash
git add src/metatron/core/config.py
git commit -m "feat(config): add RECALL_GRAPH_MAX_DEPTH setting (default 2)"
```

---

### Task 2: Enhance `recall_graph` with seed collection + BFS hop expansion

**Files:**
- Modify: `src/metatron/retrieval/channels.py:13,205-234`
- Test: `tests/unit/test_recall_channels.py:262-296`

- [ ] **Step 1: Write failing tests for enhanced recall_graph**

First, update the default `settings` MagicMock in `_make_ctx` (line 23) to include the new field:

```python
        "settings": MagicMock(recall_top_n_dense=30, recall_top_n_exact=10, recall_top_n_metadata=10, recall_top_n_graph=5, recall_graph_max_depth=2),
```

Then replace the existing graph tests in `tests/unit/test_recall_channels.py` (lines 258-296) with comprehensive tests. Add these tests after the existing `test_recall_metadata_*` tests:

```python
# ---------------------------------------------------------------------------
# recall_graph (enhanced: seed collection + BFS hop expansion)
# ---------------------------------------------------------------------------


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_collects_seeds_from_all_sources(
    mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn,
):
    """Seeds come from jira keys, title entities, person names, and graph match."""
    mock_get_ents.return_value = [{"name": "RBAC", "type": "concept"}]
    # First call: direct labels for seeds; second call: expanded labels
    mock_get_labels.side_effect = [
        [{"doc_label": "DOC-1", "entity": "RBAC"}],
        [{"doc_label": "DOC-3", "entity": "Auth"}],
    ]
    mock_get_rels.return_value = [
        {"source": "RBAC", "target": "Auth", "type": "RELATED_TO"},
    ]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-1", "memory": "t"},
        {"id": "p3", "score": 0.6, "doc_label": "DOC-3", "memory": "t"},
    ]
    ctx = _make_ctx(
        extracted_jira_keys=["MTRNIX-104"],
        extracted_title_entities=["Project Aurora"],
        detected_person=["John Smith"],
        settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=1),
    )
    results = recall_graph(ctx)
    # Verify seeds include all sources: jira key + title entity + person + graph entity
    first_call_args = mock_get_labels.call_args_list[0]
    seed_names = set(first_call_args[0][0])  # positional arg 0
    assert "MTRNIX-104" in seed_names
    assert "Project Aurora" in seed_names
    assert "John Smith" in seed_names
    assert "RBAC" in seed_names
    assert len(results) >= 1


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_hop_expansion(mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn):
    """BFS hop expansion discovers entities at depth > 1."""
    mock_get_ents.return_value = [{"name": "A"}]
    # Hop 0: direct labels for seed "A"
    # Hop 1: rels from "A" find "B"; labels for "B"
    # Hop 2: rels from "B" find "C"; labels for "C"
    mock_get_labels.side_effect = [
        [{"doc_label": "DOC-A"}],  # direct for seeds
        [{"doc_label": "DOC-B"}],  # hop 1: entity B
        [{"doc_label": "DOC-C"}],  # hop 2: entity C
    ]
    mock_get_rels.side_effect = [
        [{"source": "A", "target": "B", "type": "KNOWS"}],  # hop 1
        [{"source": "B", "target": "C", "type": "KNOWS"}],  # hop 2
    ]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.9, "doc_label": "DOC-A", "memory": "t"},
        {"id": "p2", "score": 0.8, "doc_label": "DOC-B", "memory": "t"},
        {"id": "p3", "score": 0.7, "doc_label": "DOC-C", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    # All three doc labels should be in the search
    call_args = store.search_by_doc_labels.call_args
    searched_labels = set(call_args[0][0])
    assert "DOC-A" in searched_labels
    assert "DOC-B" in searched_labels
    assert "DOC-C" in searched_labels


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_zero_depth_skips_expansion(
    mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn,
):
    """max_depth=0 means no hop expansion, only direct seed labels."""
    mock_get_ents.return_value = [{"name": "X"}]
    mock_get_labels.return_value = [{"doc_label": "DOC-X"}]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-X", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=0))
    results = recall_graph(ctx)
    mock_get_rels.assert_not_called()
    assert len(results) == 1


@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_empty_when_no_seeds(mock_get_ents, mock_get_labels, mock_get_rels):
    """No seeds from any source → empty result, no graph calls."""
    mock_get_ents.return_value = []
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    assert results == []
    mock_get_labels.assert_not_called()
    mock_get_rels.assert_not_called()


@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_graceful_on_error(mock_get_ents):
    """Exception in graph calls → empty result, no crash."""
    mock_get_ents.side_effect = Exception("Memgraph down")
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    assert results == []


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_deduplicates_labels(mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn):
    """Same doc_label from seeds and expansion → fetched only once."""
    mock_get_ents.return_value = [{"name": "A"}]
    mock_get_labels.side_effect = [
        [{"doc_label": "DOC-1"}],  # direct
        [{"doc_label": "DOC-1"}],  # expansion returns same label
    ]
    mock_get_rels.return_value = [{"source": "A", "target": "B", "type": "REL"}]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-1", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=1))
    results = recall_graph(ctx)
    searched_labels = store.search_by_doc_labels.call_args[0][0]
    assert len(searched_labels) == len(set(searched_labels)), "Labels should be deduplicated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_recall_channels.py -v -k "recall_graph" 2>&1 | tail -20`
Expected: FAIL — tests reference `get_graph_relationships` mock that doesn't exist in channels.py yet

- [ ] **Step 3: Implement enhanced recall_graph**

In `src/metatron/retrieval/channels.py`:

**3a. Update import (line 13):**

Change:
```python
from metatron.storage.graph_ops import get_doc_labels_by_entities, get_graph_entities
```
To:
```python
from metatron.storage.graph_ops import (
    get_doc_labels_by_entities,
    get_graph_entities,
    get_graph_relationships,
)
```

**3b. Replace `recall_graph` function (lines 205-234):**

```python
_MAX_FRONTIER = 50  # Cap BFS frontier to prevent explosion on highly-connected entities


def recall_graph(ctx: RecallContext) -> list[ScoredResult]:
    """Graph channel: find related documents via entity graph traversal.

    Collects seed entities from 4 sources (Jira keys, title entities,
    person names, graph entity match), then expands via iterative BFS
    hop expansion using graph relationships.
    """
    limit = ctx.settings.recall_top_n_graph if ctx.settings else 5
    max_depth = ctx.settings.recall_graph_max_depth if ctx.settings else 2
    try:
        # 1. Collect seed entity names from RecallContext
        seeds: set[str] = set()
        seeds.update(ctx.extracted_jira_keys)
        seeds.update(ctx.extracted_title_entities)
        seeds.update(ctx.detected_person)

        # 2. Graph entity match on query (existing behavior)
        query_for_ner = ctx.translated_query or ctx.original_query
        graph_ents = get_graph_entities([query_for_ner], workspace_id=ctx.workspace_id)
        seeds.update(e["name"] for e in graph_ents if "name" in e)

        if not seeds:
            return []

        # 3. Get direct doc_labels for seeds
        direct = get_doc_labels_by_entities(list(seeds), workspace_id=ctx.workspace_id)
        all_labels: set[str] = {r["doc_label"] for r in direct if "doc_label" in r}

        # 4. Iterative BFS hop expansion
        # NOTE: get_graph_relationships accepts max_depth but does NOT do multi-hop
        # internally. We always pass max_depth=1 and iterate ourselves.
        seen_entities = set(seeds)
        frontier = set(seeds)
        for _hop in range(max_depth):
            if not frontier:
                break
            rels = get_graph_relationships(
                list(frontier)[:_MAX_FRONTIER],
                workspace_id=ctx.workspace_id,
                max_depth=1,
            )
            neighbor_names = {r["source"] for r in rels} | {r["target"] for r in rels}
            frontier = neighbor_names - seen_entities
            seen_entities.update(frontier)
            if frontier:
                expanded = get_doc_labels_by_entities(
                    list(frontier)[:_MAX_FRONTIER],
                    workspace_id=ctx.workspace_id,
                )
                all_labels.update(r["doc_label"] for r in expanded if "doc_label" in r)

        if not all_labels:
            return []

        # 5. Fetch chunks, apply ACL, limit
        store = get_hybrid_store(ctx.workspace_id)
        hits = _post_filter_acl(
            store.search_by_doc_labels(list(all_labels), limit=limit),
            ctx.access_filter,
        )
        return [_qdrant_hit_to_scored(h) for h in hits[:limit]]
    except Exception:
        logger.error("recall_graph failed", workspace=ctx.workspace_id, exc_info=True)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_recall_channels.py -v 2>&1 | tail -30`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/unit/ -x -q 2>&1 | tail -15`
Expected: No failures

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/channels.py tests/unit/test_recall_channels.py
git commit -m "feat(retrieval): enhance recall_graph with seed collection + BFS hop expansion

Seeds from 4 sources: Jira keys, title entities, person names, graph match.
Iterative BFS expansion up to recall_graph_max_depth hops.
Frontier capped at 50 entities to prevent explosion."
```

---

### Task 3: Remove chunk injection from step 8 in search.py

**Files:**
- Modify: `src/metatron/retrieval/search.py:38,47-48,615-628`

- [ ] **Step 1: Write failing test — step 8 should not inject chunks into frags**

Add to `tests/unit/test_recall_channels.py` (or a new section at the bottom):

This is tested implicitly: after removing the chunk injection, the existing `test_search_trace_extended.py` and `test_error_handling.py` tests must still pass. We add one explicit test to confirm `get_related_documents` is no longer called:

```python
# In tests/unit/test_error_handling.py — verify get_related_documents is NOT imported/called
# This is verified by removing the import and running existing tests.
```

Actually, the best verification is that existing tests pass after the removal. Proceed directly to implementation.

- [ ] **Step 2: Remove chunk injection block from search.py**

In `src/metatron/retrieval/search.py`:

**2a. Remove `get_related_documents` from import (line 38):**

Change:
```python
from metatron.storage.graph_ops import (  # TODO: async migration
    get_graph_entities, get_doc_labels_by_entities, get_related_documents,
    get_entities_by_doc_labels, get_graph_relationships,
    get_relationships_at_date,
)
```
To:
```python
from metatron.storage.graph_ops import (  # TODO: async migration
    get_graph_entities, get_doc_labels_by_entities,
    get_entities_by_doc_labels, get_graph_relationships,
    get_relationships_at_date,
)
```

**2b. Remove dead constants `_REL_DOCS` and `_CTX_EXTRA` (lines 47-48):**

Delete these two lines:
```python
_REL_DOCS = int(getattr(_s, "search_related_docs_limit", 5))
_CTX_EXTRA = int(getattr(_s, "search_context_extra", 5))
```

**2c. Remove `get_related_documents` fallback and chunk injection block (lines 615-628):**

Change this block (lines 615-628):
```python
            g_docs = (get_doc_labels_by_entities(list(names), workspace_id, user_groups=user_groups)
                      if dl else get_related_documents(frags, workspace_id, user_groups=user_groups))
        # Expand context with graph-related documents
        if dl and g_docs:
            extra = [d["doc_label"] for d in g_docs if d.get("doc_label") and d["doc_label"] not in dl]
            if extra:
                for mem in get_hybrid_store(workspace_id).search_by_doc_labels(extra, limit=_REL_DOCS):
                    text = mem.get("memory") or mem.get("data") or ""
                    if len(text) > _MAX_FRAG:
                        text = text[:_MAX_FRAG] + "..."
                    th = hash(text[:200])
                    if th in seen_h or total_c + len(text) > _MAX_TOTAL:
                        continue
                    frags.append(text); seen_h.add(th); total_c += len(text)
```
To:
```python
            g_docs = get_doc_labels_by_entities(list(names), workspace_id, user_groups=user_groups) if dl else []
        # Graph docs kept as metadata only — document chunks come from recall channels
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/ -x -q 2>&1 | tail -15`
Expected: ALL PASS (some tests may need patch updates — see Task 4)

- [ ] **Step 4: Commit**

```bash
git add src/metatron/retrieval/search.py
git commit -m "refactor(search): remove chunk injection from step 8 graph enrichment

Step 8 now only collects entity/relationship metadata for LLM context.
All document-level decisions go through recall channels → reranker.
Removed: get_related_documents fallback, _REL_DOCS, _CTX_EXTRA constants."
```

---

### Task 4: Fix test patches for removed functions

**Files:**
- Modify: `tests/unit/test_search_trace_extended.py`
- Modify: `tests/unit/test_benchmarker_search_trace.py`
- Modify: `tests/unit/test_error_handling.py` (if needed)

- [ ] **Step 1: Remove `get_related_documents` patch from test_search_trace_extended.py**

In `tests/unit/test_search_trace_extended.py`, in the `_patch_search_internals()` function, remove this entry:
```python
        "get_related_documents": patch(
            f"{_SEARCH_MODULE}.get_related_documents", return_value=[],
        ),
```

- [ ] **Step 2: Remove `get_related_documents` patch from test_benchmarker_search_trace.py**

In `tests/unit/test_benchmarker_search_trace.py`, in the `_patch_search_internals()` function, remove this entry:
```python
        "get_related_documents": patch(
            f"{_SEARCH_MODULE}.get_related_documents", return_value=[],
        ),
```

- [ ] **Step 3: Check test_error_handling.py**

Verify that `test_error_handling.py` does not reference `get_related_documents`. If it does, remove the patch.

Run: `grep -n "get_related_documents" tests/unit/test_error_handling.py`

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/unit/ -x -q 2>&1 | tail -15`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_search_trace_extended.py tests/unit/test_benchmarker_search_trace.py
git commit -m "test: remove get_related_documents patches after step 8 cleanup"
```

---

### Task 5: Final verification — all tests pass, no regressions

- [ ] **Step 1: Run full unit test suite**

Run: `pytest tests/unit/ -v 2>&1 | tail -40`
Expected: ALL PASS, same count as before (±2 for removed/added graph tests)

- [ ] **Step 2: Run lint**

Run: `make lint 2>&1 | tail -10`
Expected: No errors

- [ ] **Step 3: Run typecheck**

Run: `make typecheck 2>&1 | tail -10`
Expected: No new errors

- [ ] **Step 4: Verify the pipeline trace still works**

Run: `pytest tests/unit/test_search_trace_extended.py tests/unit/test_benchmarker_search_trace.py -v 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 5: Verify error handling still works**

Run: `pytest tests/unit/test_error_handling.py -v 2>&1 | tail -20`
Expected: ALL PASS
