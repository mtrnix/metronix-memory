"""compute_signal_score — query-level normalization (MTRNIX-397, S1 / B-1).

The signal score must be normalized by the weights of the channels that actually
returned results *for the whole query* (query-level), never per-candidate — otherwise
candidates with different active channel sets would land on different scales and the
intra-query rank would be corrupted.

Rules under test:
- a channel (`dense`/`graph`/`metadata`) weight drops from the denominator iff that
  channel returned 0 results for the query;
- `metadata_weight` is kept when `exact` OR `metadata` returned (scoring uses
  `metadata = max(exact, metadata)`);
- `recency` and `balance` are NOT channels — never dropped;
- `active_channels=None` reproduces the legacy all-weights denominator exactly.
"""

from __future__ import annotations

import math

from metronix.retrieval.scoring import compute_signal_score

# Default weights (function signature): dense 0.35, graph 0.15, metadata 0.20,
# recency 0.10, balance 0.05, freshness 0.0.


def test_legacy_none_reproduces_all_weights_denominator() -> None:
    """active_channels=None (and the default) must equal the pre-MTRNIX-397 formula."""
    cs = {"dense": 0.5, "graph": 0.3, "metadata": 0.4}
    expected = (0.35 * 0.5 + 0.15 * 0.3 + 0.20 * 0.4 + 0.10 * 0.6 + 0.05 * 0.8) / 0.85
    got_explicit = compute_signal_score(cs, recency=0.6, balance=0.8, active_channels=None)
    got_default = compute_signal_score(cs, recency=0.6, balance=0.8)
    assert math.isclose(got_explicit, expected, rel_tol=1e-12)
    assert math.isclose(got_default, expected, rel_tol=1e-12)


def test_empty_channels_dropped_query_level() -> None:
    """Only dense returned for the query → denominator = dense+recency+balance (0.50).

    The empty metadata/graph weights leave the denominator, so a dense-only candidate
    scores materially higher than under the legacy all-weights (0.85) denominator.
    """
    cs = {"dense": 0.8}  # metadata/graph absent
    active = {"dense"}
    expected = (0.35 * 0.8 + 0.10 * 0.6 + 0.05 * 0.5) / (0.35 + 0.10 + 0.05)
    got = compute_signal_score(cs, recency=0.6, balance=0.5, active_channels=active)
    assert math.isclose(got, expected, rel_tol=1e-12)

    legacy = compute_signal_score(cs, recency=0.6, balance=0.5, active_channels=None)
    assert got > legacy  # the whole point of S1


def test_same_denominator_for_all_candidates_in_query() -> None:
    """Two candidates with the same active set are divided by the same denominator."""
    active = {"dense"}
    a = compute_signal_score({"dense": 0.9}, recency=0.5, balance=0.5, active_channels=active)
    b = compute_signal_score({"dense": 0.1}, recency=0.5, balance=0.5, active_channels=active)
    raw_a = 0.35 * 0.9 + 0.10 * 0.5 + 0.05 * 0.5
    raw_b = 0.35 * 0.1 + 0.10 * 0.5 + 0.05 * 0.5
    denom = 0.35 + 0.10 + 0.05
    assert math.isclose(a, raw_a / denom, rel_tol=1e-12)
    assert math.isclose(b, raw_b / denom, rel_tol=1e-12)


def test_exact_channel_retains_metadata_weight() -> None:
    """`exact` present keeps metadata_weight in denom (metadata = max(exact, metadata))."""
    active = {"dense", "exact"}
    cs = {"dense": 0.0, "exact": 0.7}
    # metadata term = max(exact, metadata) = 0.7; denom includes metadata_weight (0.20).
    expected = (0.20 * 0.7 + 0.10 * 0.0 + 0.05 * 0.0) / (0.35 + 0.20 + 0.10 + 0.05)
    got = compute_signal_score(cs, recency=0.0, balance=0.0, active_channels=active)
    assert math.isclose(got, expected, rel_tol=1e-12)


def test_metadata_channel_alone_retains_metadata_weight() -> None:
    """`metadata` (without exact) also keeps metadata_weight."""
    active = {"metadata"}
    cs = {"metadata": 0.6}
    expected = (0.20 * 0.6 + 0.10 * 1.0 + 0.05 * 1.0) / (0.20 + 0.10 + 0.05)
    got = compute_signal_score(cs, recency=1.0, balance=1.0, active_channels=active)
    assert math.isclose(got, expected, rel_tol=1e-12)


def test_recency_balance_never_dropped() -> None:
    """No channel returned, but recency/balance still form the denominator (no div-by-zero)."""
    got = compute_signal_score({}, recency=1.0, balance=1.0, active_channels=set())
    # denom = recency_weight + balance_weight = 0.15; raw = 0.10*1 + 0.05*1 = 0.15.
    assert math.isclose(got, 1.0, rel_tol=1e-12)


def test_zero_total_weight_returns_zero() -> None:
    """Degenerate guard: all weights zero → 0.0, never a ZeroDivisionError."""
    got = compute_signal_score(
        {"dense": 1.0},
        recency=1.0,
        balance=1.0,
        dense_weight=0.0,
        graph_weight=0.0,
        metadata_weight=0.0,
        recency_weight=0.0,
        balance_weight=0.0,
        active_channels=set(),
    )
    assert got == 0.0


def test_output_stays_in_unit_interval() -> None:
    """Normalized output stays in [0, 1] across active-channel combinations."""
    combos = [set(), {"dense"}, {"dense", "exact"}, {"dense", "graph", "metadata"}]
    for active in combos:
        score = compute_signal_score(
            {"dense": 1.0, "graph": 1.0, "metadata": 1.0},
            recency=1.0,
            balance=1.0,
            active_channels=active,
        )
        assert 0.0 <= score <= 1.0
