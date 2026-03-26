# Unified Multi-Signal Reranking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace sequential diversify → title_boost → cross-encoder with a unified multi-signal scoring formula that blends with cross-encoder output.

**Architecture:** Add `channel` tag to each recall result, merge preserving all channel scores, compute normalized signal score from 6 signals, blend with min-max normalized cross-encoder score for final ranking. Remove `diversify_results`, `_boost_title_matches`, `_inject_jira_key_results`, `multi_factor_score`, `tag_match`, `token_overlap`.

**Tech Stack:** Python 3.12, pytest, pydantic-settings

**Spec:** `docs/superpowers/specs/2026-03-26-unified-reranking-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `src/metatron/retrieval/channels.py` | Recall channels + merge | Modify: add `channel` to `ScoredResult`, new `MergedResult`, rewrite `merge_channels` |
| `src/metatron/retrieval/scoring.py` | Scoring functions | Rewrite: `compute_signal_score`, `compute_final_score`, `source_balance`, `normalize_rerank_scores`. Keep `recency_score` |
| `src/metatron/retrieval/search.py` | Main pipeline | Modify: replace diversify+title_boost with scoring+blend, remove dead code, update trace fields |
| `src/metatron/core/config.py` | Settings | Modify: remove `tag_weight`, add `metadata_weight`, `balance_weight`, `blend_weight`, `rerank_pool_size` |
| `src/metatron/retrieval/__init__.py` | Package exports | Modify: replace `multi_factor_score` export |
| `tests/unit/test_scoring.py` | Scoring tests | Rewrite: tests for new functions |
| `tests/unit/test_recall_channels.py` | Channel tests | Modify: update for `channel` field and new `merge_channels` |
| `tests/unit/test_diversify_results.py` | Search utility tests | Modify: remove diversify/boost tests, keep other tests |
| `tests/unit/test_jira_key_injection.py` | Jira injection tests | Delete (function removed) |
| `tests/unit/test_search_trace_extended.py` | Trace tests | Modify: update expected trace fields |
| `tests/unit/test_benchmarker_search_trace.py` | Trace tests | Modify: update patches |

---

### Task 1: Add `channel` field to `ScoredResult` and update recall functions

**Files:**
- Modify: `src/metatron/retrieval/channels.py:23-29` (ScoredResult), `:97-105` (_qdrant_hit_to_scored), `:108-121` (recall_dense), `:124-157` (recall_exact), `:163-206` (recall_metadata), `:212-275` (recall_graph)
- Test: `tests/unit/test_recall_channels.py`

- [ ] **Step 1: Write failing tests for channel field**

Add to `tests/unit/test_recall_channels.py`:

```python
class TestChannelField:
    """Each recall function tags results with its channel name."""

    @patch("metatron.retrieval.channels.get_hybrid_store")
    def test_recall_dense_sets_channel(self, mock_store) -> None:
        store = MagicMock()
        store.hybrid_search.return_value = [
            {"id": "1", "doc_label": "DOC-1", "score": 0.9, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx()
        results = recall_dense(ctx)
        assert len(results) == 1
        assert results[0]["channel"] == "dense"

    @patch("metatron.retrieval.channels.get_hybrid_store")
    def test_recall_exact_sets_channel(self, mock_store) -> None:
        store = MagicMock()
        store.search_by_doc_labels.return_value = [
            {"id": "1", "doc_label": "MTRNIX-1", "score": 0.9, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx(extracted_jira_keys=["MTRNIX-1"])
        results = recall_exact(ctx)
        assert len(results) >= 1
        assert all(r["channel"] == "exact" for r in results)

    @patch("metatron.retrieval.channels.get_hybrid_store")
    def test_recall_metadata_sets_channel(self, mock_store) -> None:
        store = MagicMock()
        store.search_by_date.return_value = [
            {"id": "1", "doc_label": "DOC-1", "score": 0.5, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx(extracted_dates=("2025-01-01", "2025-12-31"))
        results = recall_metadata(ctx)
        assert len(results) >= 1
        assert all(r["channel"] == "metadata" for r in results)

    @patch("metatron.retrieval.channels.get_graph_entities", return_value=[{"name": "Qdrant"}])
    @patch("metatron.retrieval.channels.get_doc_labels_by_entities", return_value=[{"doc_label": "DOC-1"}])
    @patch("metatron.retrieval.channels.get_graph_relationships", return_value=[])
    @patch("metatron.retrieval.channels.get_hybrid_store")
    def test_recall_graph_sets_channel(self, mock_store, _rels, _labels, _ents) -> None:
        store = MagicMock()
        store.search_by_doc_labels.return_value = [
            {"id": "1", "doc_label": "DOC-1", "score": 0.7, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx()
        results = recall_graph(ctx)
        assert len(results) >= 1
        assert all(r["channel"] == "graph" for r in results)
```

(`_make_ctx` already exists in the test file — it creates a `RecallContext` with defaults.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_recall_channels.py::TestChannelField -v`
Expected: FAIL — `KeyError: 'channel'`

- [ ] **Step 3: Add `channel` to `ScoredResult` and `_qdrant_hit_to_scored`**

In `src/metatron/retrieval/channels.py`:

Update `ScoredResult`:
```python
class ScoredResult(TypedDict):
    """Single chunk result from a recall channel."""

    chunk_id: str
    doc_label: str
    score: float
    memory: dict
    channel: str  # "dense" | "exact" | "metadata" | "graph"
```

Update `_qdrant_hit_to_scored` to accept channel:
```python
def _qdrant_hit_to_scored(hit: dict, channel: str) -> ScoredResult:
    """Convert a Qdrant store result (flat dict) to ScoredResult."""
    chunk_id = str(hit.get("id", "")) or str(uuid.uuid4())
    return ScoredResult(
        chunk_id=chunk_id,
        doc_label=hit.get("doc_label", ""),
        score=float(hit.get("score", 0.0)),
        memory=hit,
        channel=channel,
    )
```

Update each recall function to pass channel name:
- `recall_dense`: `_qdrant_hit_to_scored(h, "dense")`
- `recall_exact`: `_qdrant_hit_to_scored(h, "exact")`
- `recall_metadata`: `_qdrant_hit_to_scored(h, "metadata")`
- `recall_graph`: `_qdrant_hit_to_scored(h, "graph")`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_recall_channels.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/metatron/retrieval/channels.py tests/unit/test_recall_channels.py
git commit -m "feat: add channel field to ScoredResult for multi-signal scoring"
```

---

### Task 2: New `MergedResult` type and rewrite `merge_channels`

**Files:**
- Modify: `src/metatron/retrieval/channels.py:50-62` (merge_channels)
- Test: `tests/unit/test_recall_channels.py`

- [ ] **Step 1: Write failing tests for new merge_channels**

Add to `tests/unit/test_recall_channels.py`:

```python
from metatron.retrieval.channels import MergedResult


class TestMergeChannelsMultiSignal:
    """merge_channels preserves channel info in MergedResult."""

    def test_single_channel(self) -> None:
        results = [[
            ScoredResult(chunk_id="c1", doc_label="D1", score=0.9, memory={"m": "t"}, channel="dense"),
        ]]
        merged = merge_channels(results)
        assert len(merged) == 1
        assert merged[0]["channels"] == ["dense"]
        assert merged[0]["channel_scores"] == {"dense": 0.9}

    def test_same_chunk_two_channels(self) -> None:
        results = [
            [ScoredResult(chunk_id="c1", doc_label="D1", score=0.9, memory={"m": "t"}, channel="dense")],
            [ScoredResult(chunk_id="c1", doc_label="D1", score=0.6, memory={"m": "t"}, channel="graph")],
        ]
        merged = merge_channels(results)
        assert len(merged) == 1
        assert set(merged[0]["channels"]) == {"dense", "graph"}
        assert merged[0]["channel_scores"]["dense"] == 0.9
        assert merged[0]["channel_scores"]["graph"] == 0.6

    def test_sorted_by_max_channel_score(self) -> None:
        results = [
            [ScoredResult(chunk_id="c1", doc_label="D1", score=0.5, memory={}, channel="dense")],
            [ScoredResult(chunk_id="c2", doc_label="D2", score=0.9, memory={}, channel="exact")],
        ]
        merged = merge_channels(results)
        assert merged[0]["chunk_id"] == "c2"

    def test_memory_from_highest_scoring_channel(self) -> None:
        results = [
            [ScoredResult(chunk_id="c1", doc_label="D1", score=0.5, memory={"src": "dense"}, channel="dense")],
            [ScoredResult(chunk_id="c1", doc_label="D1", score=0.9, memory={"src": "exact"}, channel="exact")],
        ]
        merged = merge_channels(results)
        assert merged[0]["memory"]["src"] == "exact"

    def test_empty_input(self) -> None:
        assert merge_channels([]) == []
        assert merge_channels([[], []]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_recall_channels.py::TestMergeChannelsMultiSignal -v`
Expected: FAIL — `ImportError: cannot import name 'MergedResult'`

- [ ] **Step 3: Add `MergedResult` and rewrite `merge_channels`**

In `src/metatron/retrieval/channels.py`, replace `merge_channels`:

```python
class MergedResult(TypedDict):
    """Result after merging across channels — preserves all channel info."""

    chunk_id: str
    doc_label: str
    memory: dict
    channels: list[str]
    channel_scores: dict[str, float]


def merge_channels(channel_results: list[list[ScoredResult]]) -> list[MergedResult]:
    """Merge results from multiple channels, preserving all channel scores.

    If the same chunk appears from multiple channels, all channel scores are kept.
    Memory payload is taken from the highest-scoring channel entry.
    Results are sorted by max channel score descending.
    """
    accumulator: dict[str, MergedResult] = {}
    best_score: dict[str, float] = {}

    for results in channel_results:
        for r in results:
            cid = r["chunk_id"]
            if cid not in accumulator:
                accumulator[cid] = MergedResult(
                    chunk_id=cid,
                    doc_label=r["doc_label"],
                    memory=r["memory"],
                    channels=[r["channel"]],
                    channel_scores={r["channel"]: r["score"]},
                )
                best_score[cid] = r["score"]
            else:
                merged = accumulator[cid]
                if r["channel"] not in merged["channels"]:
                    merged["channels"].append(r["channel"])
                merged["channel_scores"][r["channel"]] = r["score"]
                if r["score"] > best_score[cid]:
                    merged["memory"] = r["memory"]
                    best_score[cid] = r["score"]

    return sorted(
        accumulator.values(),
        key=lambda x: max(x["channel_scores"].values()),
        reverse=True,
    )
```

- [ ] **Step 4: Fix downstream code in search.py**

In `src/metatron/retrieval/search.py`, the line after `merge_channels` is:
```python
raw = [sr["memory"] for sr in merged]
```
`MergedResult` still has `memory`, so this works unchanged. But verify `_post_diversify_count` still references `len(...)` of the right variable — it will be updated in Task 5.

- [ ] **Step 5: Run all tests**

Run: `pytest tests/unit/test_recall_channels.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/channels.py tests/unit/test_recall_channels.py
git commit -m "feat: MergedResult type preserves all channel scores in merge"
```

---

### Task 3: Rewrite `scoring.py` — new scoring functions

**Files:**
- Rewrite: `src/metatron/retrieval/scoring.py`
- Modify: `src/metatron/core/config.py:131-138`
- Modify: `src/metatron/retrieval/__init__.py`
- Rewrite: `tests/unit/test_scoring.py`

- [ ] **Step 1: Update config.py weights**

In `src/metatron/core/config.py`, replace the retrieval tuning block (lines 131-138):

```python
    # --- Retrieval tuning ---
    embedding_dim: int = 768
    rrf_k: int = 60
    dense_weight: float = 0.35
    sparse_weight: float = 0.0
    graph_weight: float = 0.15
    metadata_weight: float = 0.20
    recency_weight: float = 0.10
    balance_weight: float = 0.05
    blend_weight: float = 0.3
    rerank_pool_size: int = 50
```

Remove `tag_weight: float = 0.20`. Update `sparse_weight` default from `0.20` to `0.0`.

- [ ] **Step 2: Write failing tests for new scoring functions**

Rewrite `tests/unit/test_scoring.py`:

```python
"""Tests for retrieval/scoring.py — multi-signal scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from metatron.retrieval.scoring import (
    compute_final_score,
    compute_signal_score,
    normalize_rerank_scores,
    recency_score,
    source_balance,
)


class TestRecencyScore:
    def test_just_now(self) -> None:
        now = datetime.now(timezone.utc)
        score = recency_score(now, now)
        assert abs(score - 1.0) < 0.01

    def test_half_life(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=30)
        score = recency_score(past, now, half_life_days=30)
        assert abs(score - 0.5) < 0.01

    def test_very_old(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=365)
        score = recency_score(past, now, half_life_days=30)
        assert score < 0.01

    def test_score_between_zero_and_one(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=15)
        score = recency_score(past, now)
        assert 0.0 < score <= 1.0


class TestSourceBalance:
    def test_underrepresented_gets_bonus(self) -> None:
        # 5 jira, 1 confluence — jira is >40%, confluence is not
        type_counts = {"jira": 5, "confluence": 1}
        total = 6
        assert source_balance("confluence", type_counts, total) == 1.0

    def test_overrepresented_gets_zero(self) -> None:
        type_counts = {"jira": 5, "confluence": 1}
        total = 6
        assert source_balance("jira", type_counts, total) == 0.0

    def test_even_split_still_over_threshold(self) -> None:
        # 50% each — both exceed 40% threshold
        type_counts = {"jira": 3, "confluence": 3}
        total = 6
        assert source_balance("jira", type_counts, total) == 0.0

    def test_three_types_balanced(self) -> None:
        # 33% each — none exceeds 40%
        type_counts = {"jira": 2, "confluence": 2, "upload": 2}
        total = 6
        assert source_balance("jira", type_counts, total) == 1.0

    def test_empty_pool(self) -> None:
        assert source_balance("jira", {}, 0) == 1.0


class TestComputeSignalScore:
    def test_all_signals_present(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 0.8, "graph": 0.6, "exact": 0.7},
            recency=0.9,
            balance=1.0,
        )
        # Normalized: (0.35*0.8 + 0*0 + 0.15*0.6 + 0.20*0.7 + 0.10*0.9 + 0.05*1.0) / 0.85
        raw = 0.35*0.8 + 0.15*0.6 + 0.20*0.7 + 0.10*0.9 + 0.05*1.0
        expected = raw / 0.85
        assert abs(score - expected) < 0.001

    def test_dense_only(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0},
            recency=0.0,
            balance=0.0,
        )
        expected = (0.35 * 1.0) / 0.85
        assert abs(score - expected) < 0.001

    def test_no_channels(self) -> None:
        score = compute_signal_score(
            channel_scores={},
            recency=1.0,
            balance=1.0,
        )
        expected = (0.10 * 1.0 + 0.05 * 1.0) / 0.85
        assert abs(score - expected) < 0.001

    def test_custom_weights(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0},
            recency=0.0,
            balance=0.0,
            dense_weight=0.5,
            sparse_weight=0.0,
            graph_weight=0.1,
            metadata_weight=0.1,
            recency_weight=0.1,
            balance_weight=0.1,
        )
        expected = 0.5 / 0.9
        assert abs(score - expected) < 0.001

    def test_output_in_zero_one_range(self) -> None:
        score = compute_signal_score(
            channel_scores={"dense": 1.0, "graph": 1.0, "exact": 1.0, "metadata": 1.0},
            recency=1.0,
            balance=1.0,
        )
        assert 0.0 <= score <= 1.0


class TestNormalizeRerankScores:
    def test_basic_normalization(self) -> None:
        results = [
            {"rerank_score": 5.0},
            {"rerank_score": 3.0},
            {"rerank_score": 1.0},
        ]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0
        assert results[2]["rerank_score"] == 0.0
        assert abs(results[1]["rerank_score"] - 0.5) < 0.01

    def test_all_same_score(self) -> None:
        results = [
            {"rerank_score": 3.0},
            {"rerank_score": 3.0},
        ]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0
        assert results[1]["rerank_score"] == 1.0

    def test_single_result(self) -> None:
        results = [{"rerank_score": -2.0}]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0

    def test_negative_scores(self) -> None:
        results = [
            {"rerank_score": -1.0},
            {"rerank_score": -3.0},
        ]
        normalize_rerank_scores(results)
        assert results[0]["rerank_score"] == 1.0
        assert results[1]["rerank_score"] == 0.0

    def test_empty_list(self) -> None:
        normalize_rerank_scores([])  # should not raise


class TestComputeFinalScore:
    def test_default_blend(self) -> None:
        # blend=0.3 → 0.3*signal + 0.7*rerank
        score = compute_final_score(signal_score=1.0, rerank_score=0.0)
        assert abs(score - 0.3) < 0.01

    def test_full_rerank(self) -> None:
        score = compute_final_score(signal_score=0.0, rerank_score=1.0)
        assert abs(score - 0.7) < 0.01

    def test_custom_blend(self) -> None:
        score = compute_final_score(signal_score=0.8, rerank_score=0.6, blend_weight=0.5)
        assert abs(score - 0.7) < 0.01  # 0.5*0.8 + 0.5*0.6 = 0.7

    def test_equal_scores(self) -> None:
        score = compute_final_score(signal_score=0.5, rerank_score=0.5)
        assert abs(score - 0.5) < 0.01
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_scoring.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Rewrite `scoring.py`**

Replace `src/metatron/retrieval/scoring.py` entirely:

```python
"""Multi-signal scoring for unified reranking.

Combines channel scores (dense, sparse, graph, metadata), recency decay,
and source balance into a single normalized signal score. Optionally
blends with cross-encoder rerank score for final ranking.

Default weights (sum = 0.85, output normalized to [0,1]):
- dense:    0.35
- sparse:   0.00  (placeholder — RRF doesn't separate dense/sparse)
- graph:    0.15
- metadata: 0.20
- recency:  0.10
- balance:  0.05
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def recency_score(
    updated_at: datetime,
    now: datetime | None = None,
    half_life_days: float = 30.0,
) -> float:
    """Exponential time decay — newer documents score higher.

    A document updated half_life_days ago scores 0.5.
    Returns score in (0.0, 1.0].
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_days = max((now - updated_at).total_seconds() / 86400.0, 0.0)
    decay_rate = math.log(2) / half_life_days
    return math.exp(-decay_rate * age_days)


def source_balance(
    source_type: str,
    type_counts: dict[str, int],
    total: int,
    threshold: float = 0.4,
) -> float:
    """Return 1.0 if source type is underrepresented, 0.0 if overrepresented.

    A source type is overrepresented if it makes up > threshold of the pool.
    """
    if total == 0:
        return 1.0
    count = type_counts.get(source_type, 0)
    return 0.0 if count / total > threshold else 1.0


def compute_signal_score(
    channel_scores: dict[str, float],
    recency: float = 1.0,
    balance: float = 1.0,
    *,
    dense_weight: float = 0.35,
    sparse_weight: float = 0.0,
    graph_weight: float = 0.15,
    metadata_weight: float = 0.20,
    recency_weight: float = 0.10,
    balance_weight: float = 0.05,
) -> float:
    """Compute normalized multi-signal score for a retrieval candidate.

    All input scores should be in [0, 1] range.
    Output is normalized by sum of weights to stay in [0, 1].
    """
    vector = channel_scores.get("dense", 0.0)
    sparse = channel_scores.get("sparse", 0.0)
    graph = channel_scores.get("graph", 0.0)
    metadata = max(
        channel_scores.get("exact", 0.0),
        channel_scores.get("metadata", 0.0),
    )

    raw = (
        dense_weight * vector
        + sparse_weight * sparse
        + graph_weight * graph
        + metadata_weight * metadata
        + recency_weight * recency
        + balance_weight * balance
    )

    weight_sum = (
        dense_weight + sparse_weight + graph_weight
        + metadata_weight + recency_weight + balance_weight
    )
    return raw / weight_sum if weight_sum > 0 else 0.0


def normalize_rerank_scores(results: list[dict]) -> None:
    """Normalize rerank_score values in-place to [0, 1] via min-max.

    If all scores are equal or list has <= 1 element, all scores become 1.0.
    """
    if not results:
        return
    scores = [r.get("rerank_score", 0.0) for r in results]
    min_s = min(scores)
    max_s = max(scores)
    spread = max_s - min_s
    for r in results:
        if spread == 0:
            r["rerank_score"] = 1.0
        else:
            r["rerank_score"] = (r.get("rerank_score", 0.0) - min_s) / spread


def compute_final_score(
    signal_score: float,
    rerank_score: float,
    blend_weight: float = 0.3,
) -> float:
    """Blend multi-signal score with cross-encoder rerank score.

    blend_weight controls the mix: 0.3 means 30% signal + 70% rerank.
    """
    return blend_weight * signal_score + (1 - blend_weight) * rerank_score
```

- [ ] **Step 5: Update `__init__.py` exports**

In `src/metatron/retrieval/__init__.py`, replace `multi_factor_score` import/export:

```python
"""Retrieval package — search pipeline, scoring, entity resolution."""

from metatron.retrieval.context import assemble_context
from metatron.retrieval.fallback import GracefulRetriever
from metatron.retrieval.hybrid import rrf_fusion
from metatron.retrieval.scoring import compute_signal_score
from metatron.retrieval.search import hybrid_search_and_answer

__all__ = [
    "hybrid_search_and_answer",
    "rrf_fusion",
    "compute_signal_score",
    "assemble_context",
    "GracefulRetriever",
]
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/test_scoring.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/metatron/retrieval/scoring.py src/metatron/retrieval/__init__.py \
       src/metatron/core/config.py tests/unit/test_scoring.py
git commit -m "feat: rewrite scoring.py with compute_signal_score and blend functions"
```

---

### Task 4: Integrate scoring pipeline into `search.py`

**Files:**
- Modify: `src/metatron/retrieval/search.py` — replace diversify+title_boost block (~lines 527-537) with scoring+blend
- Modify: `tests/unit/test_diversify_results.py` — remove diversify/boost tests
- Delete: `tests/unit/test_jira_key_injection.py`
- Modify: `tests/unit/test_search_trace_extended.py` — update trace field expectations
- Modify: `tests/unit/test_benchmarker_search_trace.py` — update patches

- [ ] **Step 1: Replace pipeline block in search.py**

In `src/metatron/retrieval/search.py`, add imports at the top (near other retrieval imports):

```python
from collections import Counter
from datetime import datetime
from metatron.retrieval.scoring import (
    compute_signal_score,
    compute_final_score,
    normalize_rerank_scores,
    recency_score,
    source_balance,
)
```

Replace the block from `raw = [sr["memory"] for sr in merged]` through `_post_rerank_count = len(base)` (approximately lines 527-537) with:

```python
    # -- Multi-signal scoring --
    # Compute source type distribution once for balance bonus
    type_counts: dict[str, int] = Counter(
        _result_type(mr["memory"]) for mr in merged
    )
    total_merged = len(merged)

    # Score each candidate
    for mr in merged:
        mem = mr["memory"]
        # Parse recency from date field
        date_str = mem.get("date") or (mem.get("payload") or {}).get("date")
        rec = 1.0  # default: no penalty
        if date_str:
            try:
                dt = datetime.fromisoformat(str(date_str))
                rec = recency_score(dt)
            except (ValueError, TypeError):
                rec = 1.0
        bal = source_balance(_result_type(mem), type_counts, total_merged)
        mr["signal_score"] = compute_signal_score(
            channel_scores=mr["channel_scores"],
            recency=rec,
            balance=bal,
            dense_weight=_s.dense_weight,
            sparse_weight=_s.sparse_weight,
            graph_weight=_s.graph_weight,
            metadata_weight=_s.metadata_weight,
            recency_weight=_s.recency_weight,
            balance_weight=_s.balance_weight,
        )

    # Sort by signal score, take top pool for reranker
    merged.sort(key=lambda x: x.get("signal_score", 0), reverse=True)
    _signal_scored_count = len(merged)

    # Convert to legacy dict format for downstream
    pool_size = _s.rerank_pool_size if _s.reranker_enabled else len(merged)
    base = [mr["memory"] for mr in merged[:pool_size]]
    # Carry signal_score on memory dict for blend
    for mr, b in zip(merged[:pool_size], base):
        b["_signal_score"] = mr.get("signal_score", 0)

    _pre_rerank_count = len(base)
    if _s.reranker_enabled:
        from metatron.retrieval.reranker import rerank
        base = rerank(query=rq, results=base, top_k=len(base))
        normalize_rerank_scores(base)
        # Blend signal + rerank scores
        for r in base:
            r["_final_score"] = compute_final_score(
                signal_score=r.get("_signal_score", 0),
                rerank_score=r.get("rerank_score", 0),
                blend_weight=_s.blend_weight,
            )
        base.sort(key=lambda x: x.get("_final_score", 0), reverse=True)
        base = base[:k]
    _post_rerank_count = len(base)
```

- [ ] **Step 2: Remove dead functions from search.py**

Delete these functions from `search.py`:
- `diversify_results()` (and `_MIN_PER_SOURCE` constant)
- `_boost_title_matches()`
- `_inject_jira_key_results()`

Also remove the line `base = _boost_title_matches(rq, base, entities=entities)` and `_post_diversify_count = ...` variable/references.

- [ ] **Step 3: Update trace fields in search.py**

In the `pipeline_stages` dict (around line 627), replace:
```python
"post_diversify_count": _post_diversify_count,
```
with:
```python
"signal_scored_count": _signal_scored_count,
"rerank_pool_count": _pre_rerank_count,
```

- [ ] **Step 4: Update test_diversify_results.py**

Remove imports of `diversify_results`, `_boost_title_matches` from the import block. Remove these classes entirely:
- `TestDiversifyResults`
- `TestBoostTitleMatches`

In `TestUploadTypeSupport`, remove only the 2 methods that call `diversify_results`:
- `test_diversify_includes_upload`
- `test_diversify_three_types_including_upload`

Keep the other 3 methods in `TestUploadTypeSupport` (`test_result_type_detects_upload`, `test_collect_frags_upload_label`, `test_append_sources_upload_icon`).

Keep unchanged: `TestResultType`, `TestCollectFragsLabeling`, `TestAppendSources`, `TestDetectResponseLanguage`, `TestExtractProperNouns`, `TestSourcesToMarkdown`.

Update the import block to only import what's still needed:
```python
from metatron.retrieval.search import (
    _collect_frags, _result_type, _append_sources, _JIRA_KEY_RE,
    detect_response_language,
    extract_proper_nouns,
)
```

- [ ] **Step 5: Move `TestJiraKeyRegex` from test_jira_key_injection.py, then delete it**

Move `TestJiraKeyRegex` class from `tests/unit/test_jira_key_injection.py` into `tests/unit/test_diversify_results.py` (the `_JIRA_KEY_RE` regex is still live code used by `_build_recall_context`). Only delete `TestInjectJiraKeyResults` — that class tested the removed function.

```bash
git rm tests/unit/test_jira_key_injection.py
```

- [ ] **Step 6: Update test_search_trace_extended.py**

In `_patch_search_internals()`:

1. Remove `diversify_results` patch.
2. Replace `merge_channels` patch — it must now return `list[MergedResult]` format. The default returns empty list (most tests work with empty results). For `test_retrieved_doc_labels_populated_from_results`, override `merge_channels` in that specific test to return results with `doc_label` in `memory`.

Update `_patch_search_internals()`:
```python
"merge_channels": patch(
    f"{_SEARCH_MODULE}.merge_channels",
    return_value=[],  # default: empty merged results
),
```

Remove the old `diversify_results` patch. No need to patch individual scoring functions — they operate on the `merged` list which is empty by default.

For `test_retrieved_doc_labels_populated_from_results`, override `merge_channels` to return proper `MergedResult` dicts:
```python
patches["merge_channels"] = patch(
    f"{_SEARCH_MODULE}.merge_channels",
    return_value=[
        {"chunk_id": "c1", "doc_label": "DOC-1", "memory": {"memory": "text one", "doc_label": "DOC-1"},
         "channels": ["dense"], "channel_scores": {"dense": 0.9}},
        {"chunk_id": "c2", "doc_label": "DOC-2", "memory": {"memory": "text two", "doc_label": "DOC-2"},
         "channels": ["exact"], "channel_scores": {"exact": 0.8}},
        {"chunk_id": "c3", "doc_label": "", "memory": {"memory": "no label"},
         "channels": ["dense"], "channel_scores": {"dense": 0.5}},
    ],
)
```

Update `test_pipeline_stages_has_all_subkeys` — replace `"post_diversify_count"` with `"signal_scored_count"` and `"rerank_pool_count"` in the expected keys set.

- [ ] **Step 7: Update test_benchmarker_search_trace.py**

Same patch updates as Step 6 — replace `diversify_results` patch with `merge_channels` patch returning empty `list[MergedResult]`.

- [ ] **Step 8: Run all tests**

Run: `pytest tests/unit/test_scoring.py tests/unit/test_recall_channels.py tests/unit/test_diversify_results.py tests/unit/test_search_trace_extended.py tests/unit/test_benchmarker_search_trace.py tests/unit/test_token_budget.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_diversify_results.py \
       tests/unit/test_search_trace_extended.py tests/unit/test_benchmarker_search_trace.py
git rm tests/unit/test_jira_key_injection.py
git commit -m "feat: integrate unified scoring pipeline, remove diversify/boost/inject"
```

---

### Task 5: Run eval and verify no regression

**Files:**
- None modified — evaluation only

- [ ] **Step 1: Run full unit test suite**

Run: `pytest tests/unit/ --ignore=tests/unit/test_benchmarker_confidence.py --ignore=tests/unit/test_benchmarker_endpoints.py --ignore=tests/unit/test_benchmarker_generator.py --ignore=tests/unit/test_benchmarker_metrics.py -q`
Expected: all tests pass (no regressions from removed functions)

- [ ] **Step 2: Run eval baseline**

Run: `make eval-compare`
Record P@10, MRR, NDCG@10, Negative Accuracy results.

- [ ] **Step 3: Verify no regression**

Compare eval results with baseline from Task 3 branch. Acceptance: no metric drops more than 5% relative.

- [ ] **Step 4: Commit eval results to PR description**

Document results in PR body when creating the PR.
