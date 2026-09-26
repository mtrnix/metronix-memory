"""Replay post-recall score fusion offline from a ``pipeline_probe --trace`` dump.

``pipeline_probe --trace`` stores every merged candidate with its channel scores and
cross-encoder score. This script re-ranks those candidates with the fusion functions of
``metronix.retrieval.fusion`` (the same code the pipeline runs) under different weights,
without re-running recall or the cross-encoder, and reports the probe's metrics. It is
for sensitivity analysis only: numbers reported as results come from real pipeline runs.

The ``bridge`` mode needs extra cross-encoder calls and cannot be replayed here.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.musique.scripts.pipeline_probe import aggregate, gold_positions
from metronix.retrieval.fusion import (
    calibrated_scores,
    channel_rankings,
    parse_weights,
    ranking_from_scores,
    rrf_scores,
)


def replay_question(
    row: dict, mode: str, weights: dict[str, float], k: int = 25, rrf_k: int = 60, pool: int = 35
) -> list[str]:
    """Final top-k doc labels for one question under ``mode``."""
    cands = row["candidates"]
    merged = [{"chunk_id": c["doc_label"], "channel_scores": c["channel_scores"]} for c in cands]
    ranks = channel_rankings(merged)
    pre = rrf_scores(ranks, weights, k=rrf_k)
    ordered = sorted(cands, key=lambda c: -pre.get(c["doc_label"], 0.0))[:pool]
    labels = [c["doc_label"] for c in ordered]
    # Candidates the recorded run did not rerank keep 0 (possible only if pools differ).
    ce = {c["doc_label"]: float(c["ce"] or 0.0) for c in ordered}
    if mode == "rrf":
        pool_ranks = {c: {i: r for i, r in rs.items() if i in ce} for c, rs in ranks.items()}
        pool_ranks["rerank"] = ranking_from_scores(ce)
        final = rrf_scores(pool_ranks, weights, k=rrf_k)
    elif mode == "calibrated":
        channel_scores: dict[str, dict[str, float]] = {"rerank": ce}
        for c in ordered:
            for channel, score in c["channel_scores"].items():
                name = "metadata" if channel == "exact" else channel
                channel_scores.setdefault(name, {})[c["doc_label"]] = float(score)
        final = calibrated_scores(channel_scores, weights, labels)
    elif mode == "ce":
        final = ce
    else:
        raise ValueError(f"cannot replay mode {mode!r}")
    return sorted(labels, key=lambda label: -final.get(label, 0.0))[:k]


def replay(rows: list[dict], mode: str, weights: dict[str, float], k: int = 25) -> dict:
    scored = []
    for row in rows:
        top = replay_question(row, mode, weights, k=k)
        ranks = gold_positions(row["gold"], top)
        scored.append(
            {
                "gold": row["gold"],
                "retrieved_rank": ranks,
                # The context holds the top-k fragments whenever they fit the budget,
                # which they do for MuSiQue paragraphs at k=25.
                "context_hop0": ranks[row["gold"][0]] is not None,
                "context_last_hop": ranks[row["gold"][-1]] is not None,
                "context_both": all(v is not None for v in ranks.values()),
                "context_docs": len(top),
            }
        )
    return aggregate(scored)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=Path, help="pipeline_probe --trace --output file")
    parser.add_argument("--mode", choices=["rrf", "calibrated", "ce"], required=True)
    parser.add_argument("--weights", default="", help='e.g. "rerank=1,graph=0.5"')
    parser.add_argument("--k", type=int, default=25)
    args = parser.parse_args()
    rows = json.loads(args.trace.read_text(encoding="utf-8"))["rows"]
    weights = parse_weights(args.weights, "calibrated" if args.mode == "ce" else args.mode)
    print(
        json.dumps(
            {"mode": args.mode, "weights": weights, **replay(rows, args.mode, weights, args.k)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
