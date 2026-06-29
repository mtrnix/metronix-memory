"""Tests for retrieval/hybrid.py — Reciprocal Rank Fusion."""

from __future__ import annotations

from metronix.retrieval.hybrid import rrf_fusion


class TestRrfFusion:
    def test_empty_input(self) -> None:
        assert rrf_fusion() == []

    def test_single_list(self) -> None:
        results = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        fused = rrf_fusion(results, k=60)
        assert len(fused) == 3
        # Order should be preserved since it's the only list
        assert fused[0][0] == "a"
        assert fused[1][0] == "b"
        assert fused[2][0] == "c"

    def test_two_lists_boost_overlap(self) -> None:
        dense = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        sparse = [("b", 5.0), ("d", 4.0), ("a", 3.0)]
        fused = rrf_fusion(dense, sparse, k=60)
        # "b" appears in both at good ranks → should be first or second
        ids = [doc_id for doc_id, _ in fused]
        assert "b" in ids[:2]
        assert "a" in ids[:2]

    def test_union_merge(self) -> None:
        list1 = [("a", 1.0), ("b", 0.9)]
        list2 = [("c", 1.0), ("d", 0.9)]
        fused = rrf_fusion(list1, list2, k=60)
        ids = {doc_id for doc_id, _ in fused}
        assert ids == {"a", "b", "c", "d"}

    def test_top_k_limit(self) -> None:
        results = [(f"doc_{i}", float(i)) for i in range(100)]
        fused = rrf_fusion(results, k=60, top_k=5)
        assert len(fused) == 5

    def test_scores_are_positive(self) -> None:
        results = [("a", 0.9), ("b", 0.8)]
        fused = rrf_fusion(results, k=60)
        for _, score in fused:
            assert score > 0

    def test_original_scores_ignored(self) -> None:
        # Same rank order, different scores → same RRF output
        list_a = [("x", 100.0), ("y", 50.0)]
        list_b = [("x", 0.001), ("y", 0.0001)]
        fused_a = rrf_fusion(list_a, k=60)
        fused_b = rrf_fusion(list_b, k=60)
        assert [doc_id for doc_id, _ in fused_a] == [doc_id for doc_id, _ in fused_b]

    def test_three_lists(self) -> None:
        l1 = [("a", 1.0), ("b", 0.9)]
        l2 = [("b", 1.0), ("c", 0.9)]
        l3 = [("b", 1.0), ("a", 0.9)]
        fused = rrf_fusion(l1, l2, l3, k=60)
        # "b" is rank 1 or 2 in all three → should be first
        assert fused[0][0] == "b"
