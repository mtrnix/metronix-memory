"""Paired comparison of two ``pipeline_probe`` runs over the same questions.

For each metric the per-question difference B - A is summarised with its mean, a
bootstrap 95% confidence interval (resampling questions), and an exact two-sided sign
test on the questions where the runs differ (wins / losses). Metrics:

``recall@k``      share of the question's supporting paragraphs in the top k;
``last_hop@k``    the last-hop paragraph is in the top k;
``both_in_context``  every supporting paragraph is among the fragments.

``--subset`` restricts the comparison to question ids listed in a file (one per line),
``--exclude`` removes them; ``--hops`` keeps questions with that many supporting hops.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path


def _within(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def per_question(row: dict, metric: str) -> float:
    ranks = list(row["retrieved_rank"].values())
    if metric.startswith("recall@"):
        k = int(metric.split("@")[1])
        return sum(_within(r, k) for r in ranks) / len(ranks)
    if metric.startswith("last_hop@"):
        k = int(metric.split("@")[1])
        return float(_within(ranks[-1], k))
    if metric == "both_in_context":
        return float(row["context_both"])
    raise ValueError(metric)


def sign_test(wins: int, losses: int) -> float:
    """Exact two-sided binomial p-value for wins vs losses under p = 0.5."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_ci(diffs: list[float], samples: int = 10000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(samples))
    return means[int(0.025 * samples)], means[int(0.975 * samples) - 1]


def compare(rows_a: list[dict], rows_b: list[dict], metrics: list[str]) -> dict:
    by_a = {r["qid"]: r for r in rows_a}
    by_b = {r["qid"]: r for r in rows_b}
    qids = [q for q in by_a if q in by_b]
    out: dict = {"questions": len(qids)}
    for metric in metrics:
        a = [per_question(by_a[q], metric) for q in qids]
        b = [per_question(by_b[q], metric) for q in qids]
        diffs = [y - x for x, y in zip(a, b, strict=True)]
        wins = sum(d > 0 for d in diffs)
        losses = sum(d < 0 for d in diffs)
        lo, hi = bootstrap_ci(diffs) if diffs else (0.0, 0.0)
        out[metric] = {
            "a": round(100 * sum(a) / len(a), 2) if a else 0.0,
            "b": round(100 * sum(b) / len(b), 2) if b else 0.0,
            "diff": round(100 * sum(diffs) / len(diffs), 2) if diffs else 0.0,
            "ci95": [round(100 * lo, 2), round(100 * hi, 2)],
            "wins": wins,
            "losses": losses,
            "sign_p": round(sign_test(wins, losses), 4),
        }
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument(
        "--metrics",
        default="recall@2,recall@5,last_hop@5,both_in_context",
        help="comma-separated",
    )
    parser.add_argument("--subset", type=Path)
    parser.add_argument("--exclude", type=Path)
    parser.add_argument("--hops", type=int)
    args = parser.parse_args()

    def load(path: Path) -> list[dict]:
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
        if args.subset:
            keep = set(args.subset.read_text().split())
            rows = [r for r in rows if r["qid"] in keep]
        if args.exclude:
            drop = set(args.exclude.read_text().split())
            rows = [r for r in rows if r["qid"] not in drop]
        if args.hops:
            rows = [r for r in rows if len(r["gold"]) == args.hops]
        return rows

    result = compare(load(args.a), load(args.b), args.metrics.split(","))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
