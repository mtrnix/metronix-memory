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
from pathlib import Path

import numpy as np

from benchmarks.musique.scripts.pipeline_probe import aggregate, gold_positions
from metronix.retrieval.fusion import learned_features


def question_features(row: dict, feature_set: str) -> tuple[list[str], np.ndarray]:
    """Feature rows of a dumped question's reranked pool (``fusion.learned_features``)."""
    cands = [
        {"id": c["doc_label"], "channel_scores": c["channel_scores"], "ce": c["ce"]}
        for c in row["candidates"]
        if c.get("ce") is not None
    ]
    if not cands:
        return [], np.zeros((0, 0))
    labels, rows = learned_features(cands, feature_set)
    return labels, np.array(rows, dtype=float)


def fit(rows: list[dict], feature_set: str):
    """Scaler and logistic regression fitted on every candidate of ``rows``."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    data = [(row, *question_features(row, feature_set)) for row in rows]
    data = [d for d in data if d[1]]
    x = np.vstack([feats for _, _, feats in data])
    y = np.concatenate([[float(lbl in row["gold"]) for lbl in labels] for row, labels, _ in data])
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
    model.fit(scaler.transform(x), y)
    return scaler, model


def export_model(scaler, model, feature_set: str, trained_on: str) -> dict:
    """The JSON form ``metronix.retrieval.fusion.learned_scores`` reads."""
    return {
        "feature_set": feature_set,
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scaler.scale_],
        "coef": [float(v) for v in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "trained_on": trained_on,
    }


def cross_validate(rows: list[dict], feature_set: str, folds: int = 5, k: int = 25) -> dict:
    scored = []
    for fold in range(folds):
        train = [row for i, row in enumerate(rows) if i % folds != fold]
        test = [row for i, row in enumerate(rows) if i % folds == fold]
        scaler, model = fit(train, feature_set)
        scored += _rank(test, scaler, model, feature_set, k)
    return aggregate(scored)


def _rank(rows: list[dict], scaler, model, feature_set: str, k: int) -> list[dict]:
    scored = []
    for row in rows:
        labels, feats = question_features(row, feature_set)
        prob = model.decision_function(scaler.transform(feats)) if labels else np.array([])
        top = [labels[i] for i in np.argsort(-prob, kind="stable")][:k]
        ranks = gold_positions(row["gold"], top)
        scored.append(
            {
                "qid": row.get("qid"),
                "gold": row["gold"],
                "retrieved_rank": ranks,
                "context_rank": ranks,
                "context_hop0": ranks[row["gold"][0]] is not None,
                "context_last_hop": ranks[row["gold"][-1]] is not None,
                "context_both": all(v is not None for v in ranks.values()),
                "context_docs": len(top),
            }
        )
    return scored


def train_test(
    train_rows: list[dict], test_rows: list[dict], feature_set: str, k: int = 25
) -> tuple[dict, list[dict]]:
    """Fit on every question of ``train_rows``, rank ``test_rows`` (held-out evaluation).

    Returns the probe metrics and per-question rows in ``pipeline_probe`` shape, so the
    result can be compared with ``compare_runs.py``.
    """
    scaler, model = fit(train_rows, feature_set)
    scored = _rank(test_rows, scaler, model, feature_set, k)
    return aggregate(scored), scored


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=Path)
    parser.add_argument("--features", choices=["static", "query"], default="static")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--test", type=Path, help="fit on all of TRACE and evaluate on this held-out dump"
    )
    parser.add_argument("--output", type=Path, help="with --test: per-question rows")
    parser.add_argument(
        "--export", type=Path, help="fit on all of TRACE and write the model JSON here"
    )
    args = parser.parse_args()
    rows = json.loads(args.trace.read_text(encoding="utf-8"))["rows"]
    if args.export:
        scaler, model = fit(rows, args.features)
        args.export.write_text(
            json.dumps(export_model(scaler, model, args.features, args.trace.name), indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.export}")
        return
    if args.test:
        test_rows = json.loads(args.test.read_text(encoding="utf-8"))["rows"]
        result, scored = train_test(rows, test_rows, args.features)
        summary = {"features": args.features, "train": str(args.trace), **result}
        print(json.dumps(summary, indent=2))
        if args.output:
            args.output.write_text(
                json.dumps({"summary": summary, "rows": scored}, indent=2), encoding="utf-8"
            )
        return
    result = cross_validate(rows, args.features, args.folds)
    print(json.dumps({"features": args.features, **result}, indent=2))


if __name__ == "__main__":
    main()
