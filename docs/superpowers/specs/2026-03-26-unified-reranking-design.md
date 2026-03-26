# Unified Multi-Signal Reranking — Design Spec

> **Task 4** of the "Investigate and improve search quality" epic.
> Depends on Task 2 (recall channels) and Task 3 (graph as candidate source).

**Goal:** Replace the sequential diversify → title_boost → cross-encoder pipeline with a unified multi-signal scoring formula that blends with cross-encoder output for final ranking.

**Architecture:** Each recall channel tags results with channel origin. After merge, `compute_signal_score()` produces a single score from vector/graph/metadata/recency/balance signals. Cross-encoder reranks the top pool, then a blend formula combines both scores for final ordering.

---

## 1. Data Model Changes

### ScoredResult (channels.py)

Add `channel` field:

```python
class ScoredResult(TypedDict):
    chunk_id: str
    doc_label: str
    score: float
    memory: dict
    channel: str  # "dense" | "exact" | "metadata" | "graph"
```

Each recall function sets its own channel name.

### MergedResult (channels.py)

New type returned by `merge_channels`:

```python
class MergedResult(TypedDict):
    chunk_id: str
    doc_label: str
    memory: dict
    channels: list[str]               # e.g. ["dense", "graph"]
    channel_scores: dict[str, float]  # e.g. {"dense": 0.85, "graph": 0.6}
```

When a chunk appears in multiple channels, `merge_channels` keeps all channel scores. Initial sort order: `max(channel_scores.values())` descending.

---

## 2. Multi-Signal Scoring Formula

New function `compute_signal_score()` in `scoring.py`. Replaces `multi_factor_score()`, `diversify_results()`, and `_boost_title_matches()`.

```
raw = (
    w_vector   * vector_score   +
    w_sparse   * sparse_score   +
    w_graph    * graph_score    +
    w_metadata * metadata_score +
    w_recency  * recency_score  +
    w_balance  * balance_bonus
)
signal_score = raw / sum_of_all_weights   # normalized to [0, 1]
```

Output is normalized by dividing by the sum of **all** configured weights (not just active/non-zero signals). This intentionally penalizes candidates that score well on only one channel — a result with only a dense score gets `0.35/0.85 ≈ 0.41`, while a result with all signals at 1.0 gets `0.85/0.85 = 1.0`. This prevents single-channel results from dominating the ranking.

### Signal sources

| Signal | Source | Notes |
|--------|--------|-------|
| `vector_score` | `channel_scores.get("dense", 0)` | Primary relevance signal |
| `sparse_score` | 0.0 (placeholder) | RRF doesn't expose sparse separately; reserved for future |
| `graph_score` | `channel_scores.get("graph", 0)` | Entity graph connectivity |
| `metadata_score` | `max(channel_scores.get("exact", 0), channel_scores.get("metadata", 0))` | Covers title match, jira key, person, date |
| `recency_score` | `scoring.recency_score(date)` | Parses `"date"` string field from memory payload. Fallback: `1.0` when date is missing or unparseable |
| `balance_bonus` | 1.0 if source type < 40% of pool, else 0.0 | Computed over full merged pool before scoring (not sequentially). Source type distribution is fixed once, then each candidate checked against it |

### Recency signal details

The memory payload stores `"date"` as a string (e.g. `"2024-03-15"`), not a datetime object. `compute_signal_score` parses this string via `datetime.fromisoformat()`. If the field is missing, empty, or unparseable, `recency_score` defaults to `1.0` (no penalty — equivalent to "just updated").

### Balance bonus details

Before scoring, compute source type distribution across the full merged pool:
```python
type_counts = Counter(result_type(r) for r in all_merged)
total = len(all_merged)
overrepresented = {t for t, c in type_counts.items() if c / total > 0.4}
```
Then for each candidate: `balance_bonus = 0.0 if result_type in overrepresented else 1.0`.

This is computed once over the full pool, not sequentially. All candidates see the same distribution.

### Default weights (config.py)

| Parameter | Default | Env var |
|-----------|---------|---------|
| `dense_weight` | 0.35 | `DENSE_WEIGHT` |
| `sparse_weight` | 0.0 | `SPARSE_WEIGHT` |
| `graph_weight` | 0.15 | `GRAPH_WEIGHT` |
| `metadata_weight` | 0.20 | `METADATA_WEIGHT` |
| `recency_weight` | 0.10 | `RECENCY_WEIGHT` |
| `balance_weight` | 0.05 | `BALANCE_WEIGHT` |
| `blend_weight` | 0.3 | `BLEND_WEIGHT` |
| `rerank_pool_size` | 50 | `RERANK_POOL_SIZE` |

Remove `tag_weight` (dead — `tag_match` is unused in pipeline).

Update `sparse_weight` default from 0.20 to 0.0 (placeholder until RRF exposes sparse component separately).

Add `rerank_pool_size` — number of top signal-scored candidates sent to cross-encoder (replaces hardcoded values).

---

## 3. Cross-Encoder Blend

### Pipeline flow

```
merge_channels (preserves channel info)
  → compute source type distribution (once)
  → compute_signal_score (all ~75 candidates, normalized)
  → sort by signal_score, take top rerank_pool_size (50)
  → cross-encoder rerank (50 candidates → each gets rerank_score)
  → normalize rerank_score to [0,1] via min-max across batch
  → final_score = blend_weight * signal_score + (1 - blend_weight) * rerank_score
  → sort by final_score, take top-k (25)
```

### Blend formula

```python
def compute_final_score(signal_score: float, rerank_score: float, blend_weight: float = 0.3) -> float:
    return blend_weight * signal_score + (1 - blend_weight) * rerank_score
```

- `blend_weight=0.3` → 70% cross-encoder, 30% multi-signal
- Cross-encoder captures semantic relevance; multi-signal adds graph/metadata/balance signals it can't see

### Min-max normalization edge cases

When normalizing cross-encoder scores:
- If `min == max` (all candidates scored equally), all normalized scores become `1.0`
- If only 1 candidate, normalized score is `1.0`

### When cross-encoder is disabled

`final_score = signal_score`. No blend, multi-signal is the sole ranker. `rerank_pool_size` is ignored.

---

## 4. What Gets Removed

| Current code | Replaced by |
|-------------|-------------|
| `diversify_results()` in search.py | `balance_bonus` signal in formula |
| `_boost_title_matches()` in search.py | `metadata_score` signal (title match covered by exact channel) |
| `_inject_jira_key_results()` in search.py | Dead code (absorbed by `recall_exact` in Task 2) |
| `multi_factor_score()` in scoring.py | `compute_signal_score()` |
| `tag_match()` in scoring.py | Removed (dead code — never called in pipeline) |
| `token_overlap()` in scoring.py | Removed (dead code — never called in pipeline) |
| `tag_weight` in config.py | Removed |

## 5. What Stays Unchanged

- `_collect_frags()` — runs after reranking, as before
- `_result_type()` — still used by `_collect_frags` and by `source_balance()` computation
- `extract_title_entities()`, `extract_proper_nouns()` — still used by `_build_recall_context`
- Graph enrichment (entities/relationships for LLM context) — unchanged
- Token budget → LLM call → source append — unchanged
- ACL post-rerank hook — stays at same position (after final ranking)
- `reranker.py` — no changes to cross-encoder logic; only normalization of output scores
- `recency_score()` in scoring.py — reused as-is

---

## 6. File Changes Summary

| File | Action |
|------|--------|
| `retrieval/channels.py` | Add `channel` to `ScoredResult`, new `MergedResult` type, update `merge_channels`, each recall function sets channel |
| `retrieval/scoring.py` | Rewrite: `compute_signal_score()`, `compute_final_score()`, `source_balance()`, `normalize_scores()`. Remove `multi_factor_score`, `tag_match`, `token_overlap`. Keep `recency_score` |
| `retrieval/search.py` | Replace diversify+title_boost with scoring pipeline + blend. Remove `diversify_results`, `_boost_title_matches`, `_inject_jira_key_results`. Update trace fields |
| `core/config.py` | Remove `tag_weight`, update `sparse_weight` default to 0.0, add `metadata_weight`, `balance_weight`, `blend_weight`, `rerank_pool_size` |
| `retrieval/__init__.py` | Update exports: `compute_signal_score` replaces `multi_factor_score` |

---

## 7. Trace Logging Updates

Replace `post_diversify_count` trace field with new fields reflecting the unified pipeline:

| Old field | New field |
|-----------|-----------|
| `post_diversify_count` | `signal_scored_count` (candidates after merge) |
| — | `rerank_pool_count` (candidates sent to cross-encoder) |
| `pre_rerank_count` | kept (same meaning) |
| `post_rerank_count` | kept (same meaning, now = top-k after blend) |

---

## 8. Acceptance Criteria

- [ ] Single unified rerank stage across all candidate channels
- [ ] All signal weights configurable via env vars
- [ ] Cross-encoder operates on merged pool with blend scoring
- [ ] Signal scores normalized to [0,1] (weights divided by sum)
- [ ] `multi_factor_score()` removed, replaced by `compute_signal_score()`
- [ ] `diversify_results()`, `_boost_title_matches()`, `_inject_jira_key_results()` removed
- [ ] Trace logging fields updated for new pipeline stages
- [ ] No regression on eval test set vs. baseline (P@10, MRR, NDCG@10)
- [ ] Tests cover: scoring formula, blend, source balance, disabled cross-encoder, min-max edge cases, missing date fallback
