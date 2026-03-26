# Search Quality Tuning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete all remaining backlog items from the search quality epic — code quality cleanup, performance tuning, quality improvements — before moving to the next sprint.

**Architecture:** 10 independent tasks touching scoring, channels, classifier, and search pipeline. No new modules. All changes are surgical modifications to existing files. Grid search is a script, not a code change.

**Tech Stack:** Python 3.12, pytest, structlog, Qdrant, Memgraph

---

## Backlog Items → Tasks

| Backlog | Task | Summary |
|---------|------|---------|
| C3 | 1 | Remove dead `sparse_weight` path |
| C2 | 2 | Cache `_result_type()` in scoring loop |
| C1 | 3 | Extract scores from memory dicts into `score_map` |
| D1 | 4 | Update spec wording on weight normalization |
| Q2 | 5 | Smooth gradient for `source_balance()` |
| P2 | 6 | Tune `RERANK_POOL_SIZE` (50 → 35) + eval |
| Q3 | 7 | Confidence threshold on `signal_score` for negative queries |
| P3 | 8 | LRU cache for `recall_graph` Memgraph queries |
| P1 | 9 | Async recall channels via `asyncio.gather()` |
| Q1 | 10 | Grid search script for scoring weights |

---

## File Map

| File | Tasks | Changes |
|------|-------|---------|
| `src/metatron/retrieval/scoring.py` | 1, 2, 5 | Remove sparse_weight param, smooth source_balance |
| `src/metatron/retrieval/search.py` | 2, 3, 7, 9 | Cache _result_type, score_map, confidence filter, async channels |
| `src/metatron/retrieval/query_classifier.py` | 1 | Remove sparse_weight from all profiles |
| `src/metatron/retrieval/channels.py` | 8 | LRU cache on graph entity lookups |
| `src/metatron/core/config.py` | 6, 7 | rerank_pool_size default, min_signal_score_threshold |
| `docs/superpowers/specs/2026-03-26-unified-reranking-design.md` | 4 | Clarify normalization wording |
| `scripts/grid_search_weights.py` | 10 | New: grid search script |
| `tests/unit/test_scoring.py` | 1, 2, 5 | Tests for scoring changes |
| `tests/unit/test_search_quality_tuning.py` | 3, 7, 8 | Tests for score_map, confidence, cache |

---

### Task 1: Remove dead `sparse_weight` path

**Context:** `sparse_weight=0.0` everywhere — no recall channel produces `"sparse"` scored results. Dead code.

**Files:**
- Modify: `src/metatron/retrieval/scoring.py:60-98`
- Modify: `src/metatron/retrieval/query_classifier.py:35-90`
- Test: `tests/unit/test_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_scoring.py — add to existing file
import inspect
from metatron.retrieval.scoring import compute_signal_score

def test_compute_signal_score_has_no_sparse_weight_param():
    """sparse_weight was removed — verify it's not in the signature."""
    sig = inspect.signature(compute_signal_score)
    assert "sparse_weight" not in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_scoring.py::test_compute_signal_score_has_no_sparse_weight_param -v`
Expected: FAIL — sparse_weight still in signature

- [ ] **Step 3: Remove sparse_weight from scoring.py**

In `scoring.py`, remove:
- `sparse_weight: float = 0.0` from `compute_signal_score()` params (line 66)
- `sparse = channel_scores.get("sparse", 0.0)` (line 78)
- `+ sparse_weight * sparse` from raw calculation (line 88)
- `+ sparse_weight` from weight_sum calculation (line 96)
- Update module docstring to remove `sparse: 0.00` line

- [ ] **Step 4: Remove sparse_weight from all classifier profiles**

In `query_classifier.py`, delete the `"sparse_weight": 0.0` line from all 6 entries in `QUERY_PROFILE_WEIGHTS` dict (lines 38, 47, 56, 65, 74, 83).

- [ ] **Step 5: Update test_custom_weights in test_scoring.py**

The existing `test_custom_weights` passes `sparse_weight=0.0` explicitly. Remove that param:

```python
    def test_custom_weights(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0},
            recency=0.0,
            balance=0.0,
            dense_weight=0.5,
            graph_weight=0.1,
            metadata_weight=0.1,
            recency_weight=0.1,
            balance_weight=0.1,
        )
        expected = 0.5 / 0.9
        assert abs(score - expected) < 0.001
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/test_scoring.py tests/unit/test_query_classifier.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/metatron/retrieval/scoring.py src/metatron/retrieval/query_classifier.py tests/unit/test_scoring.py
git commit -m "refactor: remove dead sparse_weight path from scoring pipeline"
```

---

### Task 2: Cache `_result_type()` in scoring loop

**Context:** `_result_type(mem)` is called twice per merged result in `hybrid_search_and_answer()` — once for `Counter` (line 573) and once for `source_balance()` (line 589). Cache it.

**Files:**
- Modify: `src/metatron/retrieval/search.py:572-595`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_search_quality_tuning.py (new file)
def test_result_type_called_once_per_candidate():
    """_result_type should be cached — called once per merged result, not twice."""
    import ast
    import inspect
    from metatron.retrieval import search

    source = inspect.getsource(search.hybrid_search_and_answer)
    tree = ast.parse(source)
    # Count occurrences of _result_type in the scoring loop
    # After fix: should use cached type_cache dict
    assert "type_cache" in source or "_result_type(mem)" not in source.split("source_balance")[1]
```

- [ ] **Step 2: Implement — replace two calls with one cached lookup**

In `search.py`, replace lines 572-589:

```python
    # -- Multi-signal scoring --
    type_cache: dict[str, str] = {}
    for mr in merged:
        mem = mr["memory"]
        cid = mr["chunk_id"]
        type_cache[cid] = _result_type(mem)

    type_counts: dict[str, int] = Counter(type_cache.values())
    total_merged = len(merged)

    _scoring_weights = {k: v for k, v in _profile_weights.items() if k != "blend_weight"}

    for mr in merged:
        mem = mr["memory"]
        cid = mr["chunk_id"]
        date_str = mem.get("date") or (mem.get("payload") or {}).get("date")
        rec = 1.0
        if date_str:
            try:
                dt = datetime.fromisoformat(str(date_str))
                rec = recency_score(dt)
            except (ValueError, TypeError):
                rec = 1.0
        bal = source_balance(type_cache[cid], type_counts, total_merged)
        mr["signal_score"] = compute_signal_score(
            channel_scores=mr["channel_scores"],
            recency=rec,
            balance=bal,
            **_scoring_weights,
        )
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_search_quality_tuning.py tests/unit/test_scoring.py tests/unit/test_evidence_packs.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_search_quality_tuning.py
git commit -m "perf: cache _result_type lookup in scoring loop"
```

---

### Task 3: Extract scores from memory dicts into score_map

**Context:** Lines 590-614 in `search.py` mutate shared memory dicts with `b["_signal_score"]` and `r["_final_score"]`. These internal scores leak into consumer dicts. Use a separate `score_map` dict keyed by chunk_id.

**Files:**
- Modify: `src/metatron/retrieval/search.py:590-616`
- Test: `tests/unit/test_search_quality_tuning.py`

- [ ] **Step 1: Write the failing test**

```python
def test_memory_dicts_not_mutated_with_internal_scores():
    """Internal scoring keys (_signal_score, _final_score) must not leak into memory dicts."""
    import inspect
    from metatron.retrieval import search

    source = inspect.getsource(search.hybrid_search_and_answer)
    assert '["_signal_score"]' not in source
    assert '["_final_score"]' not in source
```

- [ ] **Step 2: Implement score_map**

Replace the scoring mutation pattern. After computing `mr["signal_score"]` for each merged result, create a `score_map`:

```python
    # Build score_map keyed by chunk_id (no mutation of memory dicts)
    score_map: dict[str, float] = {mr["chunk_id"]: mr.get("signal_score", 0) for mr in merged}

    merged.sort(key=lambda x: x.get("signal_score", 0), reverse=True)

    pool_size = _s.rerank_pool_size if _s.reranker_enabled else len(merged)
    base = [mr["memory"] for mr in merged[:pool_size]]

    _pre_rerank_count = len(base)
    if _s.reranker_enabled:
        from metatron.retrieval.reranker import rerank
        base = rerank(query=rq, results=base, top_k=len(base))
        normalize_rerank_scores(base)
        for r in base:
            cid = str(r.get("id", ""))
            score_map[cid] = compute_final_score(
                signal_score=score_map.get(cid, 0),
                rerank_score=r.get("rerank_score", 0),
                blend_weight=_profile_weights["blend_weight"],
            )
        base.sort(key=lambda x: score_map.get(
            str(x.get("id", "")), 0
        ), reverse=True)
    base = base[:k]
    _post_rerank_count = len(base)
```

**Note:** Each result dict preserves the `id` field through reranking, so `str(r.get("id", ""))` is the safe key for score_map lookups. No index alignment needed.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_search_quality_tuning.py tests/unit/test_evidence_packs.py tests/unit/test_search_trace_extended.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_search_quality_tuning.py
git commit -m "refactor: extract internal scores to score_map, stop mutating memory dicts"
```

---

### Task 4: Update spec wording on weight normalization

**Context:** D1 from backlog. Spec at `docs/superpowers/specs/2026-03-26-unified-reranking-design.md` already says "sum of all weights" (line 59-62). The backlog item is resolved — the spec matches the code. Just add a clarifying note.

**Files:**
- Modify: `docs/superpowers/specs/2026-03-26-unified-reranking-design.md`

- [ ] **Step 1: Add clarifying note to spec**

After line 62 (`"This intentionally penalizes candidates..."` paragraph), add:

```
> **Note (2026-03-26):** Normalization divides by sum of **all** configured weights, not just active/non-zero ones. This is intentional — single-channel results are penalized. This matches the implementation in `scoring.py:compute_signal_score()`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-03-26-unified-reranking-design.md
git commit -m "docs: clarify weight normalization in unified reranking spec"
```

---

### Task 5: Smooth gradient for `source_balance()`

**Context:** Q2 from backlog. Currently binary (0 or 1) at 40% threshold. Replace with smooth gradient: as a source type approaches the threshold, bonus decays linearly from 1.0 to 0.0.

**Files:**
- Modify: `src/metatron/retrieval/scoring.py:44-57`
- Test: `tests/unit/test_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_scoring.py
from metatron.retrieval.scoring import source_balance

def test_source_balance_smooth_gradient():
    """source_balance returns smooth values between 0 and 1, not binary."""
    # 30% of pool — under threshold, should be close to 1.0
    counts = {"jira": 3, "confluence": 7}
    score = source_balance("jira", counts, 10)
    assert 0.2 < score < 1.0  # Not exactly 1.0 — smooth decay

def test_source_balance_at_threshold_is_zero():
    """At or above threshold (40%), score is 0."""
    counts = {"jira": 4, "confluence": 6}
    assert source_balance("jira", counts, 10) == 0.0

def test_source_balance_rare_source_near_one():
    """Rare source (10%) gets score near 1.0."""
    counts = {"jira": 1, "confluence": 9}
    score = source_balance("jira", counts, 10)
    assert score > 0.7
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_scoring.py::test_source_balance_smooth_gradient -v`
Expected: FAIL — current binary returns exactly 1.0 for 30%

- [ ] **Step 3: Implement smooth gradient**

```python
def source_balance(
    source_type: str,
    type_counts: dict[str, int],
    total: int,
    threshold: float = 0.4,
) -> float:
    """Return smooth penalty for overrepresented source types.

    Score decays linearly from 1.0 (absent) to 0.0 (at threshold).
    Sources above the threshold get 0.0.
    """
    if total == 0:
        return 1.0
    ratio = type_counts.get(source_type, 0) / total
    if ratio >= threshold:
        return 0.0
    return 1.0 - (ratio / threshold)
```

- [ ] **Step 4: Update existing TestSourceBalance tests for smooth gradient**

The smooth gradient changes the contract — 4 of 5 existing tests need new assertions:

```python
class TestSourceBalance:
    def test_underrepresented_gets_bonus(self) -> None:
        # ratio = 1/6 = 0.167 → 1.0 - (0.167/0.4) ≈ 0.583
        type_counts = {"jira": 5, "confluence": 1}
        score = source_balance("confluence", type_counts, 6)
        assert 0.5 < score < 0.7

    def test_overrepresented_gets_zero(self) -> None:
        # ratio = 5/6 = 0.833 → >= threshold → 0.0
        type_counts = {"jira": 5, "confluence": 1}
        assert source_balance("jira", type_counts, 6) == 0.0

    def test_even_split_still_over_threshold(self) -> None:
        # ratio = 3/6 = 0.5 → >= threshold → 0.0
        type_counts = {"jira": 3, "confluence": 3}
        assert source_balance("jira", type_counts, 6) == 0.0

    def test_three_types_balanced(self) -> None:
        # ratio = 2/6 = 0.333 → 1.0 - (0.333/0.4) ≈ 0.167
        type_counts = {"jira": 2, "confluence": 2, "upload": 2}
        score = source_balance("jira", type_counts, 6)
        assert 0.1 < score < 0.3

    def test_empty_pool(self) -> None:
        assert source_balance("jira", {}, 0) == 1.0
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_scoring.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/scoring.py tests/unit/test_scoring.py
git commit -m "feat: smooth gradient for source_balance (linear decay to threshold)"
```

---

### Task 6: Tune RERANK_POOL_SIZE (50 → 35)

**Context:** P2 from backlog. Cross-encoder processes 50 candidates. Reduce to 35 — lower inference cost. Verify via eval-compare.

**Files:**
- Modify: `src/metatron/core/config.py:142`

- [ ] **Step 1: Change default**

```python
# config.py line 142
rerank_pool_size: int = 35  # was 50
```

- [ ] **Step 2: Run eval-compare**

Run: `make eval-compare`
Expected: P@10/MRR/NDCG deltas within ±0.02 (acceptable variance)

- [ ] **Step 3: If metrics regress >2%, revert to 40 and re-test**

- [ ] **Step 4: Commit**

```bash
git add src/metatron/core/config.py
git commit -m "perf: reduce RERANK_POOL_SIZE from 50 to 35"
```

---

### Task 7: Confidence threshold for negative/vague queries

**Context:** Q3 from backlog. Negative accuracy = 0%. All queries return 10 docs even when nothing is relevant. Add a minimum `signal_score` threshold — if the best candidate is below it, return a "no information found" response.

**Files:**
- Modify: `src/metatron/core/config.py`
- Modify: `src/metatron/retrieval/search.py`
- Test: `tests/unit/test_search_quality_tuning.py`

- [ ] **Step 1: Add config field**

```python
# config.py — add near rerank_pool_size
min_signal_score: float = 0.0  # 0.0 = disabled (all results returned). Set > 0 to filter low-confidence results.
```

- [ ] **Step 2: Write the failing test**

```python
def test_low_confidence_results_filtered_when_threshold_set():
    """When min_signal_score > 0, candidates below threshold are dropped."""
    # This test will be integration-level — mock the scoring to produce
    # low scores, verify that base list is filtered before LLM call.
    import inspect
    from metatron.retrieval import search
    source = inspect.getsource(search.hybrid_search_and_answer)
    assert "min_signal_score" in source
```

- [ ] **Step 3: Implement confidence filter in search.py**

After `merged.sort(...)` and before `base = [mr["memory"] for mr in merged[:pool_size]]`, add:

```python
    # -- Confidence filter: drop candidates below threshold --
    if _s.min_signal_score > 0:
        merged = [mr for mr in merged if mr.get("signal_score", 0) >= _s.min_signal_score]
        if not merged:
            no_info = "I don't have enough information to answer this question."
            if lang.lower() == "russian":
                no_info = "У меня недостаточно информации для ответа на этот вопрос."
            if return_trace:
                return {
                    "answer": no_info,
                    "source_results": [],
                    "fragments": [],
                    "graph_entities": [],
                    "graph_relations": [],
                    "graph_docs": [],
                    "pipeline_stages": {
                        "original_query": rq,
                        "translated_query": sq,
                        "expanded_query": eq,
                        "detected_language": lang,
                        "recall_dense_count": len(dense_results),
                        "recall_exact_count": len(exact_results),
                        "recall_metadata_count": len(metadata_results),
                        "recall_graph_count": len(graph_results),
                        "recall_total_unique": 0,
                        "pre_rerank_count": 0,
                        "post_rerank_count": 0,
                        "signal_scored_count": total_merged,
                        "rerank_pool_count": 0,
                        "fragment_count": 0,
                        "primary_fragment_count": 0,
                        "supporting_fragment_count": 0,
                        "token_budget_used": 0,
                        "query_profile": classification["profile"],
                        "query_profile_method": classification["method"],
                        "query_profile_confidence": classification["confidence"],
                    },
                    "retrieved_doc_labels": [],
                }
            return no_info
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_search_quality_tuning.py tests/unit/test_evidence_packs.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/metatron/core/config.py src/metatron/retrieval/search.py tests/unit/test_search_quality_tuning.py
git commit -m "feat: add min_signal_score threshold for low-confidence query filtering"
```

**Note:** Default is 0.0 (disabled). Optimal threshold TBD via grid search (Task 10). Enable by setting `METATRON_MIN_SIGNAL_SCORE=0.15` (or whatever value grid search finds).

---

### Task 8: LRU cache for `recall_graph` Memgraph queries

**Context:** P3 from backlog. `get_graph_entities()` and `get_doc_labels_by_entities()` hit Memgraph on every search. Add LRU cache with workspace-scoped key.

**Files:**
- Modify: `src/metatron/retrieval/channels.py:247-310`
- Test: `tests/unit/test_search_quality_tuning.py`

- [ ] **Step 1: Write the failing test**

```python
def test_recall_graph_caches_entity_lookups():
    """Second call with same seeds should hit cache, not Memgraph."""
    from unittest.mock import patch, MagicMock
    from metatron.retrieval.channels import recall_graph, RecallContext, _cached_get_graph_entities

    ctx = RecallContext(
        original_query="test",
        translated_query="test",
        expanded_query="test",
        detected_language="en",
        workspace_id="ws1",
        access_filter=None,
        settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2),
        extracted_jira_keys=["MTRNIX-104"],
        extracted_title_entities=[],
        extracted_dates=None,
        detected_person=[],
        is_activity_query=False,
    )

    with patch("metatron.retrieval.channels.get_graph_entities") as mock_ents, \
         patch("metatron.retrieval.channels.get_doc_labels_by_entities") as mock_labels, \
         patch("metatron.retrieval.channels.get_graph_relationships") as mock_rels, \
         patch("metatron.retrieval.channels.get_hybrid_store") as mock_store:
        mock_ents.return_value = [{"name": "Auth"}]
        mock_labels.return_value = [{"doc_label": "jira:MTRNIX-104"}]
        mock_rels.return_value = []
        mock_store.return_value.search_by_doc_labels.return_value = []

        _cached_get_graph_entities.cache_clear()
        recall_graph(ctx)
        recall_graph(ctx)

        # get_graph_entities called only once (second call hits cache)
        assert mock_ents.call_count == 1
```

- [ ] **Step 2: Implement LRU cache in channels.py**

Add at module level:

```python
from functools import lru_cache

# Cache graph entity lookups — key is (workspace_id, frozenset(query_texts))
# maxsize=128 covers typical concurrent workspaces * query variety
@lru_cache(maxsize=128)
def _cached_get_graph_entities(
    query_texts: tuple[str, ...], workspace_id: str | None,
) -> tuple[dict, ...]:
    return tuple(get_graph_entities(list(query_texts), workspace_id=workspace_id))

```

Then in `recall_graph()`, replace:
```python
graph_ents = get_graph_entities([query_for_ner], workspace_id=ctx.workspace_id)
```
with:
```python
graph_ents = list(_cached_get_graph_entities((query_for_ner,), ctx.workspace_id))
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_search_quality_tuning.py tests/unit/test_recall_channels.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/metatron/retrieval/channels.py tests/unit/test_search_quality_tuning.py
git commit -m "perf: LRU cache for graph entity lookups in recall_graph"
```

---

### Task 9: Async recall channels via `asyncio.gather()`

**Context:** P1 from backlog. 4 recall channels run sequentially. Each makes independent Qdrant/Memgraph calls. Wrap in async + gather for parallel execution. Since `hybrid_search_and_answer()` is sync (called via `asyncio.to_thread()`), use `asyncio.run()` for the parallel gather.

**Files:**
- Modify: `src/metatron/retrieval/search.py:562-566`
- Test: `tests/unit/test_search_quality_tuning.py`

- [ ] **Step 1: Write the failing test**

```python
def test_recall_channels_run_in_parallel():
    """Recall channels should use asyncio.gather, not sequential calls."""
    import inspect
    from metatron.retrieval import search
    source = inspect.getsource(search.hybrid_search_and_answer)
    # After implementation, should contain gather or _run_recall_channels
    assert "gather" in source or "_run_recall_channels" in source
```

- [ ] **Step 2: Implement parallel recall**

Add helper function in `search.py`:

```python
from concurrent.futures import ThreadPoolExecutor

_recall_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="recall")


def _run_recall_channels(ctx: RecallContext) -> tuple[list, list, list, list]:
    """Run 4 recall channels in parallel using thread pool.

    Each channel is sync (Qdrant/Memgraph clients are sync), so we use
    threads for true parallelism. Returns (dense, exact, metadata, graph).
    """
    futures = [
        _recall_executor.submit(recall_dense, ctx),
        _recall_executor.submit(recall_exact, ctx),
        _recall_executor.submit(recall_metadata, ctx),
        _recall_executor.submit(recall_graph, ctx),
    ]
    return tuple(f.result() for f in futures)
```

Replace lines 562-566:
```python
    # -- Run 4 recall channels in parallel --
    dense_results, exact_results, metadata_results, graph_results = _run_recall_channels(recall_ctx)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_search_quality_tuning.py tests/unit/test_evidence_packs.py tests/unit/test_search_trace_extended.py -v`
Expected: All PASS

- [ ] **Step 4: Run eval to verify no regression from parallelization**

Run: `make eval`
Expected: Metrics within ±0.01 of previous run (parallelization doesn't change results, only latency)

- [ ] **Step 5: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_search_quality_tuning.py
git commit -m "perf: parallel recall channels via ThreadPoolExecutor"
```

---

### Task 10: Grid search script for scoring weights

**Context:** Q1 from backlog. Write a script that systematically tests weight combinations and finds the optimal set for each profile. Uses the existing eval infrastructure.

**Files:**
- Create: `scripts/grid_search_weights.py`
- Modify: `Makefile` (add `grid-search` target)

- [ ] **Step 1: Write the grid search script**

```python
#!/usr/bin/env python3
"""Grid search for optimal scoring weights per query profile.

Systematically tests weight combinations using the eval test set
and reports best-performing weights by MRR + NDCG@10.

Usage:
    python scripts/grid_search_weights.py                    # search all profiles
    python scripts/grid_search_weights.py --profile execution  # search one profile
    python scripts/grid_search_weights.py --metric mrr         # optimize for MRR
    python scripts/grid_search_weights.py --top 5              # show top 5 results
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Stub benchmark_qed
if "benchmark_qed" not in sys.modules:
    _mock = MagicMock()
    for _name in [
        "benchmark_qed", "benchmark_qed.autoe",
        "benchmark_qed.autoe.assertion_scores",
        "benchmark_qed.autod", "benchmark_qed.autod.data_model",
        "benchmark_qed.autod.data_model.text_unit",
        "benchmark_qed.autod.data_processor",
        "benchmark_qed.autod.data_processor.embedding",
        "benchmark_qed.autod.sampler",
        "benchmark_qed.autod.sampler.clustering",
        "benchmark_qed.autod.sampler.clustering.kmeans",
        "benchmark_qed.autoq", "benchmark_qed.autoq.data_model",
        "benchmark_qed.autoq.data_model.question",
        "benchmark_qed.autoq.question_gen",
        "benchmark_qed.autoq.question_gen.data_questions",
        "benchmark_qed.autoq.question_gen.data_questions.global_question_gen",
        "benchmark_qed.autoq.question_gen.data_questions.local_question_gen",
    ]:
        sys.modules[_name] = _mock

from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS


def _weight_grid(step: float = 0.05) -> list[dict[str, float]]:
    """Generate weight combinations that sum to ~0.85 (excluding blend)."""
    values = [round(v, 2) for v in [i * step for i in range(int(0.5 / step) + 1)]]
    combos = []
    for dense, graph, metadata, recency, balance in itertools.product(
        values, values, values, values, [0.05],
    ):
        total = dense + graph + metadata + recency + balance
        if 0.80 <= total <= 0.90:
            combos.append({
                "dense_weight": dense,
                "graph_weight": graph,
                "metadata_weight": metadata,
                "recency_weight": recency,
                "balance_weight": balance,
            })
    return combos


def _blend_grid(step: float = 0.05) -> list[float]:
    """Generate blend_weight values."""
    return [round(v, 2) for v in [i * step for i in range(1, 10)]]


def main():
    parser = argparse.ArgumentParser(description="Grid search for scoring weights")
    parser.add_argument("--profile", default=None, help="Single profile to search")
    parser.add_argument("--metric", default="combined",
                        choices=["mrr", "ndcg", "precision", "combined"],
                        help="Metric to optimize")
    parser.add_argument("--top", type=int, default=3, help="Show top N results")
    parser.add_argument("--step", type=float, default=0.10,
                        help="Weight grid step size (default 0.10)")
    parser.add_argument("--workspace", default="MTRNIX")
    args = parser.parse_args()

    profiles = [args.profile] if args.profile else list(QUERY_PROFILE_WEIGHTS.keys())
    weight_combos = _weight_grid(step=args.step)
    blend_values = _blend_grid(step=args.step)

    print(f"Grid: {len(weight_combos)} signal combos × {len(blend_values)} blend values")
    print(f"Profiles: {profiles}")
    print(f"Optimizing: {args.metric}")
    print()

    # Import eval infrastructure — uses run_eval's internal API
    # The grid search script calls hybrid_search_and_answer directly
    # with return_trace=True to get per-query metrics
    from metatron.retrieval.search import hybrid_search_and_answer

    # Load eval set from the benchmarker test set
    from metatron.benchmarker.services.eval import load_eval_set
    eval_set = load_eval_set(args.workspace)
    if not eval_set:
        print("ERROR: No eval set found.")
        return

    best_per_profile: dict[str, dict] = {}

    for profile in profiles:
        print(f"\n{'='*60}")
        print(f"Profile: {profile}")
        print(f"{'='*60}")

        results = []
        total = len(weight_combos) * len(blend_values)

        for i, (weights, blend) in enumerate(
            itertools.product(weight_combos, blend_values)
        ):
            full_weights = {**weights, "blend_weight": blend}
            # Temporarily override profile weights
            QUERY_PROFILE_WEIGHTS[profile] = full_weights

            metrics = run_eval_queries(eval_set, args.workspace, profile_filter=profile)
            score = _compute_objective(metrics, args.metric)

            results.append({"weights": full_weights, "metrics": metrics, "score": score})

            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{total}] best so far: {max(r['score'] for r in results):.4f}")

        results.sort(key=lambda x: x["score"], reverse=True)
        best_per_profile[profile] = results[0]

        print(f"\nTop {args.top} for {profile}:")
        for j, r in enumerate(results[:args.top]):
            w = r["weights"]
            m = r["metrics"]
            print(f"  #{j+1}: score={r['score']:.4f} "
                  f"P@10={m.get('precision_at_k', 0):.4f} "
                  f"MRR={m.get('mrr', 0):.4f} "
                  f"NDCG={m.get('ndcg_at_k', 0):.4f}")
            print(f"       weights: {json.dumps(w)}")

    # Summary
    print(f"\n{'='*60}")
    print("RECOMMENDED WEIGHTS")
    print(f"{'='*60}")
    for profile, best in best_per_profile.items():
        print(f"\n{profile}:")
        print(f"  {json.dumps(best['weights'], indent=4)}")


def _compute_objective(metrics: dict, metric: str) -> float:
    if metric == "mrr":
        return metrics.get("mrr", 0)
    elif metric == "ndcg":
        return metrics.get("ndcg_at_k", 0)
    elif metric == "precision":
        return metrics.get("precision_at_k", 0)
    else:  # combined
        return (
            0.4 * metrics.get("mrr", 0)
            + 0.4 * metrics.get("ndcg_at_k", 0)
            + 0.2 * metrics.get("precision_at_k", 0)
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add Makefile target**

```makefile
grid-search:
	.venv/bin/python scripts/grid_search_weights.py --workspace $(or $(WORKSPACE),MTRNIX) --step 0.10
```

- [ ] **Step 3: Test the script runs**

Run: `python scripts/grid_search_weights.py --help`
Expected: Usage printed, no errors

- [ ] **Step 4: Commit**

```bash
git add scripts/grid_search_weights.py Makefile
git commit -m "feat: add grid search script for scoring weight optimization"
```

**Note:** Actual grid search run is a post-merge activity (takes 30+ minutes per profile). Script provides the infrastructure; optimal weights are applied in a follow-up commit.

---

## Execution Order

Tasks are independent except:
- Task 2 before Task 3 (both modify same lines in search.py)
- Task 6 needs eval infrastructure running

Recommended: 1 → 5 → 2 → 3 → 4 → 7 → 8 → 9 → 6 → 10

Run eval after Task 9 (all code changes done) to get combined delta.
