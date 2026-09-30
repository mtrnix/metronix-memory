"""Gold coverage of the candidate pool of ``pipeline_probe`` runs.

The pool is every merged candidate the reranker sees. Per run: the share of the
questions' gold passages in the pool, questions whose last-hop passage is in it, the
mean pool size, and the gold passages only the graph channel contributed.

Reads full ``--trace`` dumps (``rows[*].candidates``) or the compact per-question fields
``pool_gold`` / ``pool_graph_only_gold`` / ``pool_size`` that ``pool_fields`` derives
from them (the form kept under ``benchmarks/musique/results/``).
"""

from __future__ import annotations

import json
from pathlib import Path


def pool_fields(row: dict) -> dict:
    """Compact pool summary of one traced question."""
    gold = set(row["gold"])
    labels = {c["doc_label"] for c in row["candidates"]}
    graph_only = {
        c["doc_label"]
        for c in row["candidates"]
        if c["doc_label"] in gold and set(c["channel_scores"]) == {"graph"}
    }
    return {
        "pool_gold": sorted(labels & gold),
        "pool_graph_only_gold": sorted(graph_only),
        "pool_size": len(labels),
    }


def coverage(rows: list[dict]) -> dict | None:
    """Pool coverage of a run, or None when the rows carry no pool information."""
    if not rows:
        return None
    if "candidates" in rows[0]:
        rows = [{**row, **pool_fields(row)} for row in rows]
    elif "pool_gold" not in rows[0]:
        return None
    n = len(rows)
    return {
        "questions": n,
        "gold_share": round(
            100 * sum(len(r["pool_gold"]) / len(set(r["gold"])) for r in rows) / n, 2
        ),
        "last_hop_in_pool": sum(r["gold"][-1] in r["pool_gold"] for r in rows),
        "pool_size": round(sum(r["pool_size"] for r in rows) / n, 1),
        "graph_only_gold": sum(len(r["pool_graph_only_gold"]) for r in rows),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", type=Path, nargs="+", help="pipeline_probe JSON outputs")
    args = parser.parse_args()
    print(
        f"{'run':44s} {'n':>5s} {'gold %':>7s} {'last hop':>8s} {'pool':>6s} {'graph-only':>10s}"
    )
    for path in args.runs:
        result = coverage(json.loads(path.read_text(encoding="utf-8"))["rows"])
        if result is None:
            continue
        print(
            f"{path.stem:44s} {result['questions']:5d} {result['gold_share']:7.2f} "
            f"{result['last_hop_in_pool']:8d} {result['pool_size']:6.1f} "
            f"{result['graph_only_gold']:10d}"
        )


if __name__ == "__main__":
    main()
