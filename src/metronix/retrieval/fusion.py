"""Alternative score-fusion strategies for the hybrid search pipeline (#497).

The production ranking (``METRONIX_RETRIEVAL_FUSION_MODE=signal``, the default) orders
candidates by ``compute_signal_score`` and then blends that with the min-max normalised
cross-encoder score (``compute_final_score``). The channel scores it combines live on
unrelated scales -- hybrid RRF values for dense (at most ``2 / (rrf_k + 1)``, about
0.033), personalized-PageRank probability mass or a constant ``1.0`` for graph, and a
cross-encoder probability -- and the ``mixed`` profile gives graph weight 0, so a
candidate found only by the graph channel carries no graph evidence into the ranking.

The modes here are opt-in and leave ``signal`` untouched:

``rrf``
    Weighted reciprocal rank fusion (Cormack et al., 2009) over the per-channel rankings
    and, after rerank, the cross-encoder ranking. Only ranks are used, so the scale
    mismatch disappears; every channel votes with the same weight by default.
``calibrated``
    Per-channel calibration followed by a convex combination (Bruch et al., TOIS 2023,
    "TM2C2"): dense and graph scores are divided by their per-query maximum (theoretical
    minimum 0), the cross-encoder keeps its sigmoid probability instead of being min-max
    stretched over the pool, and the three are mixed with fixed weights.
``bridge``
    Chain-conditioned cross-encoder scoring for graph candidates. A bridge paragraph of a
    multi-hop question shares no terms with the question, so the cross-encoder, which
    scores each passage against the question alone, ranks it low. For every candidate the
    graph channel found, this mode also scores it against the question *extended with
    the anchor passage it hangs off* (the best cross-encoder passage that shares an
    entity with it) and keeps the chain score ``P(anchor) * P(candidate | question +
    anchor)`` when that beats its own score -- the product-of-hops path score used by
    multi-hop retrievers such as PathRetriever and Beam Retrieval, here zero-shot with
    the existing cross-encoder.

All functions are pure; ``search.py`` wires them in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

FUSION_MODES = ("signal", "rrf", "calibrated", "bridge")

# Channels that carry a query-level ranking. "exact" and "metadata" hits are
# filter matches with constant scores; they are fused as one "metadata" list.
_RANKED_CHANNELS = ("dense", "graph", "metadata")

# Untuned priors, fixed before any measurement: RRF gives every ranking one vote;
# the convex combination gives the cross-encoder half of the mass and splits the
# rest evenly between the recall channels.
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "rrf": {"rerank": 1.0, "dense": 1.0, "graph": 1.0, "metadata": 1.0},
    "calibrated": {"rerank": 0.5, "dense": 0.25, "graph": 0.25, "metadata": 0.25},
    "bridge": {"rerank": 0.5, "dense": 0.25, "graph": 0.25, "metadata": 0.25},
}


def resolve_mode(mode: str | None) -> str:
    """Known fusion mode, else the production default ``signal``."""
    return mode if mode in FUSION_MODES else "signal"


def parse_weights(spec: str, mode: str) -> dict[str, float]:
    """``"rerank=1,graph=0.5"`` on top of the mode's defaults; malformed parts are ignored."""
    weights = dict(DEFAULT_WEIGHTS.get(mode, {}))
    for part in (spec or "").split(","):
        name, sep, value = part.partition("=")
        if not sep:
            continue
        try:
            weights[name.strip()] = float(value)
        except ValueError:
            continue
    return weights


def channel_rankings(merged: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """1-based rank of every candidate within each channel that returned it.

    Ranks follow the channel score (descending). Tied scores share the best rank
    ("1224" competition ranking), so a channel that emits a constant score -- the BFS
    graph channel, exact/metadata scroll hits -- ranks all its hits first instead of
    inventing an order from point IDs.
    """
    per_channel: dict[str, list[tuple[str, float]]] = {}
    for mr in merged:
        scores = mr.get("channel_scores") or {}
        for channel, score in scores.items():
            name = "metadata" if channel == "exact" else channel
            if name not in _RANKED_CHANNELS:
                continue
            per_channel.setdefault(name, []).append((mr["chunk_id"], float(score)))
    rankings: dict[str, dict[str, int]] = {}
    for channel, items in per_channel.items():
        best: dict[str, float] = {}
        for cid, score in items:
            best[cid] = max(score, best.get(cid, float("-inf")))
        ordered = sorted(best.items(), key=lambda kv: -kv[1])
        ranks: dict[str, int] = {}
        prev_score: float | None = None
        prev_rank = 0
        for position, (cid, score) in enumerate(ordered, 1):
            rank = prev_rank if prev_score is not None and score == prev_score else position
            ranks[cid] = rank
            prev_score, prev_rank = score, rank
        rankings[channel] = ranks
    return rankings


def ranking_from_scores(scores: Mapping[str, float]) -> dict[str, int]:
    """1-based competition ranking of ids by descending score."""
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    ranks: dict[str, int] = {}
    prev_score: float | None = None
    prev_rank = 0
    for position, (cid, score) in enumerate(ordered, 1):
        rank = prev_rank if prev_score is not None and score == prev_score else position
        ranks[cid] = rank
        prev_score, prev_rank = score, rank
    return ranks


def rrf_scores(
    rankings: Mapping[str, Mapping[str, int]],
    weights: Mapping[str, float],
    k: int = 60,
) -> dict[str, float]:
    """Weighted RRF: ``sum_c w_c / (k + rank_c(d))`` over the rankings that contain d."""
    fused: dict[str, float] = {}
    for channel, ranks in rankings.items():
        weight = float(weights.get(channel, 0.0))
        if weight <= 0.0:
            continue
        for cid, rank in ranks.items():
            fused[cid] = fused.get(cid, 0.0) + weight / (k + rank)
    return fused


def max_normalize(scores: Mapping[str, float]) -> dict[str, float]:
    """Divide by the per-query maximum (theoretical minimum 0); non-positive -> 0."""
    top = max((s for s in scores.values() if s > 0.0), default=0.0)
    if top <= 0.0:
        return {cid: 0.0 for cid in scores}
    return {cid: max(s, 0.0) / top for cid, s in scores.items()}


def calibrated_scores(
    channel_scores: Mapping[str, Mapping[str, float]],
    weights: Mapping[str, float],
    candidates: Iterable[str],
) -> dict[str, float]:
    """Convex combination of per-channel calibrated scores.

    ``channel_scores[c][id]`` are raw scores; each channel except ``rerank`` is divided
    by its per-query maximum, ``rerank`` is used as is (a cross-encoder probability).
    A candidate absent from a channel scores 0 there. Only channels with at least one
    score contribute to the denominator, so the result stays in [0, 1].
    """
    normalized = {
        channel: (dict(scores) if channel == "rerank" else max_normalize(scores))
        for channel, scores in channel_scores.items()
        if scores
    }
    total_weight = sum(float(weights.get(c, 0.0)) for c in normalized)
    fused: dict[str, float] = {}
    for cid in candidates:
        raw = sum(
            float(weights.get(c, 0.0)) * scores.get(cid, 0.0) for c, scores in normalized.items()
        )
        fused[cid] = raw / total_weight if total_weight > 0 else 0.0
    return fused


def pick_anchor(
    candidate_entities: set[str],
    anchors: Sequence[tuple[str, set[str]]],
) -> str | None:
    """First anchor (in the given order) sharing an entity with the candidate.

    ``anchors`` are ``(chunk_id, entity names)`` sorted by cross-encoder score, so the
    result is the strongest passage the graph connects the candidate to.
    """
    if not candidate_entities:
        return None
    for cid, entities in anchors:
        if entities & candidate_entities:
            return cid
    return None


def bridge_query(query: str, anchor_text: str, max_chars: int = 1200) -> str:
    """The question extended with the anchor passage, for conditional scoring."""
    anchor = " ".join(anchor_text.split())
    if len(anchor) > max_chars:
        anchor = anchor[:max_chars]
    return f"{query}\n{anchor}"


def chain_score(anchor_prob: float, conditional_prob: float) -> float:
    """Path score of a two-passage chain: P(anchor | q) * P(candidate | q + anchor)."""
    return max(anchor_prob, 0.0) * max(conditional_prob, 0.0)
