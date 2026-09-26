"""Cross-validated learned fusion over ``pipeline_probe --trace`` candidate dumps.

Estimates how much a learned (logistic-regression) combination of the channel evidence
could gain over the hand-set fusions, as a headroom check for #497. Every candidate of
every question becomes one example (label: it is a supporting paragraph). Folds are split
by question, so no question contributes to the model that ranks it.

Feature sets:

``static``   cross-encoder log-odds and reciprocal rank, dense and graph scores
             (max-normalised per query), reciprocal ranks and presence flags;
``query``    ``static`` plus query-conditioned interactions (MoR-style confidence
             signals: top cross-encoder probability, its margin over the second,
             the graph channel's share of mass on its top document), each multiplied
             into the graph and dense features, so the model can weight channels per query.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from benchmarks.musique.scripts.pipeline_probe import aggregate, gold_positions
from metronix.retrieval.fusion import channel_rankings, max_normalize, ranking_from_scores


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def question_features(row: dict, feature_set: str) -> tuple[list[str], np.ndarray]:
    cands = [c for c in row["candidates"] if c.get("ce") is not None]
    labels = [c["doc_label"] for c in cands]
    merged = [{"chunk_id": c["doc_label"], "channel_scores": c["channel_scores"]} for c in cands]
    ranks = channel_rankings(merged)
    ce = {c["doc_label"]: float(c["ce"]) for c in cands}
    ce_rank = ranking_from_scores(ce)
    dense = max_normalize({c["doc_label"]: c["channel_scores"].get("dense", 0.0) for c in cands})
    graph = max_normalize({c["doc_label"]: c["channel_scores"].get("graph", 0.0) for c in cands})
    ce_sorted = sorted(ce.values(), reverse=True) + [0.0, 0.0]
    graph_raw = [c["channel_scores"].get("graph", 0.0) for c in cands]
    graph_share = max(graph_raw) / sum(graph_raw) if sum(graph_raw) > 0 else 0.0
    query_feats = [ce_sorted[0], ce_sorted[0] - ce_sorted[1], graph_share]
    rows = []
    for label in labels:
        in_dense = float(label in ranks.get("dense", {}))
        in_graph = float(label in ranks.get("graph", {}))
        base = [
            _logit(ce[label]),
            1.0 / (60 + ce_rank[label]),
            dense[label],
            1.0 / (60 + ranks["dense"][label]) if in_dense else 0.0,
            in_dense,
            graph[label],
            1.0 / (60 + ranks["graph"][label]) if in_graph else 0.0,
            in_graph,
        ]
        if feature_set == "query":
            channel = [dense[label], in_dense, graph[label], in_graph]
            base += [q * f for q in query_feats for f in channel]
        rows.append(base)
    return labels, np.array(rows, dtype=float)


def cross_validate(rows: list[dict], feature_set: str, folds: int = 5, k: int = 25) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    data = [(row, *question_features(row, feature_set)) for row in rows]
    scored = []
    for fold in range(folds):
        train = [d for i, d in enumerate(data) if i % folds != fold]
        test = [d for i, d in enumerate(data) if i % folds == fold]
        x = np.vstack([feats for _, _, feats in train])
        y = np.concatenate(
            [[float(lbl in row["gold"]) for lbl in labels] for row, labels, _ in train]
        )
        scaler = StandardScaler().fit(x)
        model = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
        model.fit(scaler.transform(x), y)
        for row, labels, feats in test:
            prob = model.predict_proba(scaler.transform(feats))[:, 1]
            top = [labels[i] for i in np.argsort(-prob)][:k]
            ranks = gold_positions(row["gold"], top)
            scored.append(
                {
                    "gold": row["gold"],
                    "retrieved_rank": ranks,
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
    parser.add_argument("trace", type=Path)
    parser.add_argument("--features", choices=["static", "query"], default="static")
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()
    rows = json.loads(args.trace.read_text(encoding="utf-8"))["rows"]
    result = cross_validate(rows, args.features, args.folds)
    print(json.dumps({"features": args.features, **result}, indent=2))


if __name__ == "__main__":
    main()
