"""Tests for adaptive RRF fusion functions."""

from metronix.retrieval.hybrid import compute_adaptive_k, compute_jaccard_overlap


def test_jaccard_identical():
    """Same IDs in both lists → Jaccard = 1.0."""
    a = [("x", 0.9), ("y", 0.8), ("z", 0.7)]
    b = [("x", 5.0), ("y", 4.0), ("z", 3.0)]
    assert compute_jaccard_overlap(a, b) == 1.0


def test_jaccard_disjoint():
    """No common IDs → Jaccard = 0.0."""
    a = [("a", 0.9), ("b", 0.8)]
    b = [("c", 5.0), ("d", 4.0)]
    assert compute_jaccard_overlap(a, b) == 0.0


def test_jaccard_partial():
    """Partial overlap → exact Jaccard value."""
    # A = {a, b, c}, B = {b, c, d} → intersection = {b, c}, union = {a, b, c, d}
    a = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
    b = [("b", 5.0), ("c", 4.0), ("d", 3.0)]
    assert compute_jaccard_overlap(a, b) == 2.0 / 4.0


def test_jaccard_empty():
    """Both lists empty → 0.0 (not division by zero)."""
    assert compute_jaccard_overlap([], []) == 0.0


def test_adaptive_k_high_overlap():
    """High overlap (>= threshold_high) → returns k_low."""
    assert (
        compute_adaptive_k(
            overlap=0.8,
            k_low=20,
            k_high=80,
            threshold_low=0.2,
            threshold_high=0.7,
        )
        == 20
    )


def test_adaptive_k_low_overlap():
    """Low overlap (<= threshold_low) → returns k_high."""
    assert (
        compute_adaptive_k(
            overlap=0.1,
            k_low=20,
            k_high=80,
            threshold_low=0.2,
            threshold_high=0.7,
        )
        == 80
    )


def test_adaptive_k_interpolation():
    """Mid overlap → interpolated value between k_low and k_high."""
    k = compute_adaptive_k(
        overlap=0.45,
        k_low=20,
        k_high=80,
        threshold_low=0.2,
        threshold_high=0.7,
    )
    # overlap=0.45, ratio = (0.45-0.2)/(0.7-0.2) = 0.5
    # k = 80 + 0.5*(20-80) = 80 - 30 = 50
    assert k == 50
    assert 20 <= k <= 80
