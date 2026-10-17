"""Channel scores must be on one scale before the weighted sum (#497, #453).

``recall_dense`` returns RRF scores (at most ~2/61 = 0.033), while the filter-based
``graph`` / ``exact`` / ``metadata`` channels return a constant 1.0. Without rescaling,
a candidate found only by one of the constant channels outranks the best dense hit.
"""

from __future__ import annotations

import pytest

from metronix.retrieval.channels import ScoredResult, merge_channels
from metronix.retrieval.scoring import compute_signal_score, rescale_dense_channel

RRF_K = 60
BEST_RRF = 2 / (RRF_K + 1)  # rank 1 in both the dense and the sparse leg


def _hit(chunk_id: str, channel: str, score: float) -> ScoredResult:
    return ScoredResult(
        chunk_id=chunk_id, doc_label=chunk_id, score=score, memory={}, channel=channel
    )


def _ranked_ids(merged: list[dict], active: set[str]) -> list[str]:
    scored = {
        m["chunk_id"]: compute_signal_score(m["channel_scores"], active_channels=active)
        for m in merged
    }
    return sorted(scored, key=scored.__getitem__, reverse=True)


def _merge(constant_channel: str) -> list[dict]:
    dense = [_hit("best_dense", "dense", BEST_RRF), _hit("weak_dense", "dense", 0.5 * BEST_RRF)]
    constant = [_hit("filter_only", constant_channel, 1.0)]
    channels = {
        "graph": [[], [], constant],
        "exact": [[], constant, []],
        "metadata": [constant, [], []],
    }
    return merge_channels([dense, *channels[constant_channel]])


@pytest.mark.parametrize("constant_channel", ["graph", "exact", "metadata"])
def test_default_scale_lets_constant_channel_displace_best_dense_hit(constant_channel):
    """Characterisation of the current default: documents the #497 behaviour."""
    merged = _merge(constant_channel)
    active = {"dense", constant_channel}
    assert _ranked_ids(merged, active)[0] == "filter_only"


@pytest.mark.parametrize("constant_channel", ["graph", "exact", "metadata"])
def test_rescaled_dense_hit_outranks_constant_channel_hit(constant_channel):
    merged = rescale_dense_channel(_merge(constant_channel))
    active = {"dense", constant_channel}
    assert _ranked_ids(merged, active)[0] == "best_dense"


def test_rescale_keeps_dense_order_and_maps_best_to_one():
    merged = rescale_dense_channel(_merge("graph"))
    dense = {
        m["chunk_id"]: m["channel_scores"]["dense"]
        for m in merged
        if "dense" in m["channel_scores"]
    }
    assert dense["best_dense"] == pytest.approx(1.0)
    assert dense["weak_dense"] == pytest.approx(0.5)


def test_rescale_does_not_mutate_input_and_leaves_other_channels():
    merged = _merge("graph")
    before = [dict(m["channel_scores"]) for m in merged]
    rescaled = rescale_dense_channel(merged)
    assert [m["channel_scores"] for m in merged] == before
    filter_only = next(m for m in rescaled if m["chunk_id"] == "filter_only")
    assert filter_only["channel_scores"] == {"graph": 1.0}


def test_rescale_without_dense_hits_is_a_noop():
    merged = merge_channels([[], [], [], [_hit("g", "graph", 1.0)]])
    assert rescale_dense_channel(merged) == merged


def test_rescale_handles_all_zero_dense_scores():
    merged = merge_channels([[_hit("z", "dense", 0.0)]])
    assert rescale_dense_channel(merged)[0]["channel_scores"]["dense"] == 0.0
