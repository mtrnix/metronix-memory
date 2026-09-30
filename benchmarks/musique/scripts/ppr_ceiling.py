"""Ceiling of the PPR graph channel with known anchors: does the walk reach the next hop?

The production PPR channel anchors on the dense top documents, collects their entities
as seeds, loads a bounded subgraph around them and ranks documents by personalized
PageRank. This probe replaces the dense anchors with the gold hop-0 passage (plus,
optionally, ``--extra-anchors`` of the question's own distractors, which stand in for
the other dense top-5 documents) and reports where the hop-1 gold passage lands among
the channel's documents, anchors excluded. It isolates the graph and the walk from the
dense retriever, so it runs on a workspace whose graph is loaded without any vectors.

Configurations (same code paths as ``recall_graph_ppr_async``):

``paths``      production subgraph (``get_ppr_subgraph``: two-hop expansion cut at
               ``--max-nodes`` in traversal order);
``specific``   ``get_ppr_subgraph_specific`` (least-mentioned seeds first, hubs above
               ``--hub-cap`` skipped, up to ``--max-docs`` documents);

each with the ``subgraph`` (production: uniform over the subgraph's entities) and
``seeds`` (seed entities only) teleport.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

TELEPORTS = ("subgraph", "seeds")
SUBGRAPHS = ("paths", "specific")


def rank_excluding(scores: dict[str, float], target: str, exclude: set[str]) -> int | None:
    """1-based rank of ``target`` by descending score, ties by label, ``exclude`` removed."""
    order = [
        label
        for label in sorted(scores, key=lambda label: (-scores[label], label))
        if label not in exclude
    ]
    return order.index(target) + 1 if target in order else None


def summarize(ranks: list[int | None], latencies: list[float]) -> dict:
    n = len(ranks)
    out: dict = {"questions": n, "in_subgraph": sum(r is not None for r in ranks)}
    for k in (1, 5, 30):
        out[f"next_hop@{k}"] = sum(r is not None and r <= k for r in ranks)
    if latencies:
        ordered = sorted(latencies)
        out["latency_median_s"] = round(statistics.median(ordered), 3)
        out["latency_p90_s"] = round(ordered[int(0.9 * (len(ordered) - 1))], 3)
    return out


def main() -> None:
    import argparse
    import logging

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--extra-anchors", type=int, default=0, help="distractors as anchors")
    parser.add_argument("--subgraph", choices=SUBGRAPHS, default="paths")
    parser.add_argument("--teleport", choices=TELEPORTS, default="subgraph")
    parser.add_argument("--max-nodes", type=int, default=500)
    parser.add_argument("--max-docs", type=int, default=100)
    parser.add_argument("--hub-cap", type=int, default=200)
    parser.add_argument("--alpha", type=float, default=0.85)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    from metronix.retrieval.ppr import WeightedEdge, document_scores, personalized_pagerank
    from metronix.storage.graph_ops import (
        get_entities_by_doc_labels,
        get_entity_node_ids,
        get_ppr_subgraph,
        get_ppr_subgraph_specific,
    )

    with args.manifest.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()][: args.limit]

    ranks: list[int | None] = []
    latencies: list[float] = []
    per_question = []
    for row in rows:
        gold = [h["doc_label"] for h in row["hops"]]
        if len(gold) < 2:
            continue
        anchors = [gold[0], *row.get("distractor_doc_labels", [])[: args.extra_anchors]]
        entities = get_entities_by_doc_labels(anchors, workspace_id=args.workspace)
        seeds = sorted({e["name"] for e in entities if e.get("name")})
        started = time.perf_counter()
        if args.subgraph == "specific":
            nodes, edges = get_ppr_subgraph_specific(
                seeds, workspace_id=args.workspace, max_docs=args.max_docs, hub_cap=args.hub_cap
            )
        else:
            nodes, edges = get_ppr_subgraph(
                seeds, workspace_id=args.workspace, max_nodes=args.max_nodes
            )
        teleport = {node: 1.0 for node, label in nodes.items() if label is None}
        if args.teleport == "seeds":
            seed_ids = get_entity_node_ids(seeds, args.workspace)
            teleport = {node: 1.0 for node in teleport if node in seed_ids} or teleport
        scores = (
            document_scores(
                personalized_pagerank(
                    [WeightedEdge(*edge) for edge in edges],
                    teleport,
                    alpha=args.alpha,
                    max_iterations=30,
                    tolerance=1e-6,
                ),
                nodes,
            )
            if edges
            else {}
        )
        latencies.append(time.perf_counter() - started)
        rank = rank_excluding(scores, gold[1], set(anchors))
        ranks.append(rank)
        per_question.append({"qid": row["qid"], "next_hop_rank": rank, "seeds": len(seeds)})

    summary = {
        "workspace": args.workspace,
        "subgraph": args.subgraph,
        "teleport": args.teleport,
        "anchors": 1 + args.extra_anchors,
        **summarize(ranks, latencies),
    }
    print(json.dumps(summary))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"summary": summary, "rows": per_question}, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
