"""Tests for two-phase grid search (scripts/grid_search_weights.py)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from grid_search_weights import (
    _blend_grid,
    _compute_objective,
    _weight_grid,
    load_cache,
    search_from_cache,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    chunk_id: str,
    doc_label: str,
    dense: float = 0.5,
    graph: float = 0.0,
    exact: float = 0.0,
    metadata: float = 0.0,
    recency: float = 1.0,
    balance: float = 1.0,
    rerank_score_raw: float = 0.0,
    source_type: str = "confluence",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_label": doc_label,
        "source_type": source_type,
        "channel_scores": {
            "dense": dense,
            "graph": graph,
            "exact": exact,
            "metadata": metadata,
        },
        "recency": recency,
        "balance": balance,
        "rerank_score_raw": rerank_score_raw,
    }


def _make_cache(queries: dict) -> dict:
    return {
        "meta": {
            "workspace": "TEST",
            "timestamp": "2026-03-27T00:00:00+00:00",
            "rerank_cache_size": 50,
            "query_count": len(queries),
        },
        "queries": queries,
    }


# ---------------------------------------------------------------------------
# Weight grid generation
# ---------------------------------------------------------------------------


class TestWeightGrid:
    def test_grid_returns_nonempty(self):
        combos = _weight_grid(step=0.10)
        assert len(combos) > 0

    def test_grid_sum_in_range(self):
        combos = _weight_grid(step=0.10)
        for c in combos:
            total = sum(c.values())
            assert 0.80 <= total <= 0.90, f"Sum out of range: {total}"

    def test_grid_all_keys_present(self):
        combos = _weight_grid(step=0.10)
        expected_keys = {
            "dense_weight",
            "graph_weight",
            "metadata_weight",
            "recency_weight",
            "balance_weight",
        }
        for c in combos:
            assert set(c.keys()) == expected_keys

    def test_blend_grid(self):
        blends = _blend_grid(step=0.10)
        assert len(blends) > 0
        assert all(0.0 < b < 1.0 for b in blends)

    def test_fine_step_more_combos(self):
        coarse = _weight_grid(step=0.10)
        fine = _weight_grid(step=0.05)
        assert len(fine) > len(coarse)


# ---------------------------------------------------------------------------
# Cache serialization round-trip
# ---------------------------------------------------------------------------


class TestCacheSerialization:
    def test_save_and_load_roundtrip(self):
        cache = _make_cache(
            {
                "q1": {
                    "text": "test query",
                    "expected_doc_labels": ["DOC-1"],
                    "category": "mixed",
                    "profile": "mixed",
                    "candidates": [
                        _make_candidate("c1", "DOC-1", dense=0.8, rerank_score_raw=1.5),
                        _make_candidate("c2", "DOC-2", dense=0.3, rerank_score_raw=0.5),
                    ],
                },
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # save_cache writes to eval_results/ relative to script
            # Use load_cache with explicit path instead
            path = Path(tmpdir) / "cache.json"
            path.write_text(json.dumps(cache, indent=2, default=str))

            loaded = load_cache(str(path))
            assert loaded["meta"]["workspace"] == "TEST"
            assert len(loaded["queries"]) == 1
            assert len(loaded["queries"]["q1"]["candidates"]) == 2

    def test_load_cache_glob(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = _make_cache(
                {
                    "q1": {
                        "text": "test",
                        "expected_doc_labels": ["DOC-1"],
                        "category": "mixed",
                        "profile": "mixed",
                        "candidates": [],
                    }
                }
            )
            (Path(tmpdir) / "grid_cache_TEST_2026-01.json").write_text(
                json.dumps(cache),
            )
            (Path(tmpdir) / "grid_cache_TEST_2026-02.json").write_text(
                json.dumps(cache),
            )
            loaded = load_cache(str(Path(tmpdir) / "grid_cache_TEST_*.json"))
            # Should load the last (most recent by sort)
            assert loaded is not None

    def test_load_cache_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_cache("/nonexistent/path/*.json")


# ---------------------------------------------------------------------------
# search_from_cache
# ---------------------------------------------------------------------------


class TestSearchFromCache:
    def test_known_signals_best_weights(self):
        """Dense-heavy candidate should win when dense is expected."""
        cache = _make_cache(
            {
                "q1": {
                    "text": "documentation query",
                    "expected_doc_labels": ["DOC-A"],
                    "category": "documentation",
                    "profile": "documentation",
                    "candidates": [
                        _make_candidate(
                            "c1",
                            "DOC-A",
                            dense=0.95,
                            graph=0.0,
                            recency=1.0,
                            balance=1.0,
                            rerank_score_raw=2.0,
                        ),
                        _make_candidate(
                            "c2",
                            "DOC-B",
                            dense=0.1,
                            graph=0.9,
                            recency=1.0,
                            balance=1.0,
                            rerank_score_raw=0.5,
                        ),
                        _make_candidate(
                            "c3",
                            "DOC-C",
                            dense=0.05,
                            graph=0.0,
                            recency=1.0,
                            balance=1.0,
                            rerank_score_raw=0.1,
                        ),
                    ],
                },
            }
        )

        best = search_from_cache(
            cache,
            step=0.10,
            profile_filter="documentation",
            metric="combined",
            top=1,
            k=3,
        )

        assert "documentation" in best
        assert best["documentation"]["score"] > 0

    def test_zero_candidates(self):
        """Empty candidate list should not crash."""
        cache = _make_cache(
            {
                "q1": {
                    "text": "empty query",
                    "expected_doc_labels": ["DOC-A"],
                    "category": "mixed",
                    "profile": "mixed",
                    "candidates": [],
                },
            }
        )

        best = search_from_cache(
            cache,
            step=0.10,
            profile_filter="mixed",
            metric="combined",
            top=1,
            k=10,
        )
        assert "mixed" in best
        assert best["mixed"]["score"] == 0.0

    def test_single_candidate(self):
        """Single candidate should produce valid metrics."""
        cache = _make_cache(
            {
                "q1": {
                    "text": "single",
                    "expected_doc_labels": ["DOC-A"],
                    "category": "mixed",
                    "profile": "mixed",
                    "candidates": [
                        _make_candidate(
                            "c1",
                            "DOC-A",
                            dense=0.9,
                            rerank_score_raw=1.0,
                        ),
                    ],
                },
            }
        )

        best = search_from_cache(
            cache,
            step=0.10,
            profile_filter="mixed",
            metric="mrr",
            top=1,
            k=10,
        )
        assert "mixed" in best
        # MRR should be 1.0 since single relevant doc at position 1
        assert best["mixed"]["score"] == 1.0

    def test_profile_filter(self):
        """Filtering by profile should only return that profile."""
        cache = _make_cache(
            {
                "q1": {
                    "text": "exec query",
                    "expected_doc_labels": ["DOC-A"],
                    "category": "execution",
                    "profile": "execution",
                    "candidates": [
                        _make_candidate("c1", "DOC-A", dense=0.9, rerank_score_raw=1.0),
                    ],
                },
                "q2": {
                    "text": "doc query",
                    "expected_doc_labels": ["DOC-B"],
                    "category": "documentation",
                    "profile": "documentation",
                    "candidates": [
                        _make_candidate("c2", "DOC-B", dense=0.8, rerank_score_raw=0.5),
                    ],
                },
            }
        )

        best = search_from_cache(
            cache,
            step=0.10,
            profile_filter="execution",
            metric="combined",
            top=1,
            k=10,
        )
        assert list(best.keys()) == ["execution"]


# ---------------------------------------------------------------------------
# Objective function
# ---------------------------------------------------------------------------


class TestComputeObjective:
    def test_mrr_mode(self):
        metrics = {"mrr": 0.8, "ndcg_at_k": 0.5, "precision_at_k": 0.3}
        assert _compute_objective(metrics, "mrr") == 0.8

    def test_ndcg_mode(self):
        metrics = {"mrr": 0.8, "ndcg_at_k": 0.5, "precision_at_k": 0.3}
        assert _compute_objective(metrics, "ndcg") == 0.5

    def test_precision_mode(self):
        metrics = {"mrr": 0.8, "ndcg_at_k": 0.5, "precision_at_k": 0.3}
        assert _compute_objective(metrics, "precision") == 0.3

    def test_combined_mode(self):
        metrics = {"mrr": 0.8, "ndcg_at_k": 0.5, "precision_at_k": 0.3}
        expected = 0.4 * 0.8 + 0.4 * 0.5 + 0.2 * 0.3
        assert abs(_compute_objective(metrics, "combined") - expected) < 1e-10
