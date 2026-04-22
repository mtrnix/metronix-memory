"""compute_signal_score — freshness signal (MTRNIX-313).

Flag-off invariant: ``freshness_weight=0.0`` (default) produces a score
identical to Phase A regardless of what ``freshness`` is — this is the
most important guarantee because it means shipping the signal is safe.
"""

from __future__ import annotations

import math

from metatron.retrieval.scoring import compute_signal_score


def test_freshness_weight_zero_is_identical_to_phase_a() -> None:
    """Phase A callers pass only (channel_scores, recency, balance).
    The Phase B formula with weight=0.0 must yield the same number.
    """
    before = compute_signal_score(
        {"dense": 0.5, "graph": 0.3, "metadata": 0.4},
        recency=0.6,
        balance=0.8,
    )
    after = compute_signal_score(
        {"dense": 0.5, "graph": 0.3, "metadata": 0.4},
        recency=0.6,
        balance=0.8,
        freshness=0.2,
        freshness_weight=0.0,
    )
    # Exact equality: weight=0.0 means the term drops out of numerator AND
    # denominator, so no fp drift is introduced.
    assert math.isclose(before, after, rel_tol=1e-12, abs_tol=1e-12)


def test_freshness_contributes_when_weight_positive() -> None:
    """Fresher doc beats stale doc when the weight is engaged."""
    s_fresh = compute_signal_score(
        {"dense": 0.5},
        recency=0.5,
        balance=0.5,
        freshness=1.0,
        freshness_weight=0.3,
    )
    s_stale = compute_signal_score(
        {"dense": 0.5},
        recency=0.5,
        balance=0.5,
        freshness=0.2,
        freshness_weight=0.3,
    )
    assert s_fresh > s_stale


def test_score_stays_in_unit_interval() -> None:
    """Normalized output stays in [0, 1] under any combination."""
    for w in [0.0, 0.05, 0.3, 0.6]:
        for f in [0.0, 0.25, 0.5, 0.75, 1.0]:
            score = compute_signal_score(
                {"dense": 1.0, "graph": 1.0, "metadata": 1.0},
                recency=1.0,
                balance=1.0,
                freshness=f,
                freshness_weight=w,
            )
            assert 0.0 <= score <= 1.0


def test_no_channels_no_crash() -> None:
    """Empty channel_scores dict returns a well-defined value."""
    score = compute_signal_score({}, freshness=0.5, freshness_weight=0.1)
    assert 0.0 <= score <= 1.0


def test_all_zero_weights_returns_zero() -> None:
    """Degenerate all-zero weights → 0.0 (defined, not NaN)."""
    score = compute_signal_score(
        {"dense": 1.0},
        dense_weight=0.0,
        graph_weight=0.0,
        metadata_weight=0.0,
        recency_weight=0.0,
        balance_weight=0.0,
        freshness=1.0,
        freshness_weight=0.0,
    )
    assert score == 0.0
