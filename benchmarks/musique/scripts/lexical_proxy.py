"""Model-free proxy of graph + first-stage fusion: BM25, the PPR channel, rank fusion.

The production first stage (nomic-embed-text + SPLADE) and cross-encoder need model
downloads; this proxy needs only a loaded graph and the HippoRAG corpus file. Per
question it ranks the corpus with BM25 (Okapi, k1 = 0.9, b = 0.4, over
``title\\ntext``), takes the BM25 top 5 as the PPR anchors, runs the PPR channel under
each subgraph / teleport setting (anchors kept or excluded, the ``ppr`` / ``ppr-novel``
distinction) and reports:

* **pool coverage**: share of gold passages in BM25 top 30 plus the channel's top 5,
  against BM25 top 35 (same pool size) -- what a reranker could work with;
* **weighted RRF** of BM25 top 30 and the channel's top 5, with the graph weight chosen
  on the even-index questions (tune) and evaluated on the odd ones (confirm), paired
  sign test against BM25 alone -- what rank fusion without a reranker achieves.

It is a proxy: BM25 is not the production retriever and there is no cross-encoder.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections import Counter
from pathlib import Path

CHANNELS = {
    # name: (subgraph builder, teleport)
    "prod": ("paths", "subgraph"),
    "seeds": ("paths", "seeds"),
    "specific": ("specific", "seeds"),
    # anchors weighted by their BM25 rank (METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=ranked)
    "ranked": ("specific", "ranked"),
}
GRAPH_WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 over a fixed corpus (scipy sparse, one matrix product per query)."""

    def __init__(self, docs: dict[str, str], k1: float = 0.9, b: float = 0.4) -> None:
        import numpy as np
        import scipy.sparse as sp

        self.labels = sorted(docs)
        self.vocab: dict[str, int] = {}
        rows, cols, vals = [], [], []
        lengths = []
        for i, label in enumerate(self.labels):
            toks = tokens(docs[label])
            lengths.append(len(toks))
            for term, count in Counter(toks).items():
                rows.append(i)
                cols.append(self.vocab.setdefault(term, len(self.vocab)))
                vals.append(count)
        n = len(self.labels)
        tf = sp.csr_matrix((vals, (rows, cols)), shape=(n, len(self.vocab))).tocoo()
        df = np.bincount(tf.col, minlength=len(self.vocab))
        idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        dl = np.asarray(lengths, dtype=float)
        norm = k1 * (1 - b + b * dl[tf.row] / dl.mean())
        weights = tf.data * (k1 + 1) / (tf.data + norm) * idf[tf.col]
        self._np = np
        self.matrix = sp.csr_matrix((weights, (tf.col, tf.row)), shape=(len(self.vocab), n))

    def top(self, query: str, k: int) -> list[str]:
        ids = [self.vocab[t] for t in tokens(query) if t in self.vocab]
        if not ids:
            return []
        scores = self._np.asarray(self.matrix[ids].sum(axis=0)).ravel()
        k = min(k, len(scores))
        top = self._np.argpartition(-scores, k - 1)[:k]
        return [self.labels[i] for i in sorted(top, key=lambda i: (-scores[i], self.labels[i]))]


def weighted_rrf(lists: list[tuple[list[str], float]], k: int = 60) -> list[str]:
    fused: dict[str, float] = {}
    for ranked, weight in lists:
        for rank, label in enumerate(ranked, 1):
            fused[label] = fused.get(label, 0.0) + weight / (k + rank)
    return sorted(fused, key=lambda label: (-fused[label], label))


def recall_at(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold)


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2**n)


def analyse(rows: list[dict], gold: dict[str, set[str]], last: dict[str, str]) -> dict:
    """Pool coverage and tuned weighted RRF from per-question channel lists."""
    out: dict = {"questions": len(rows), "coverage": {}, "rrf": {}}

    def coverage(pools: list[set[str]]) -> dict:
        return {
            "gold_share": round(
                100
                * sum(
                    len(p & gold[r["qid"]]) / len(gold[r["qid"]])
                    for p, r in zip(pools, rows, strict=True)
                )
                / len(rows),
                2,
            ),
            "last_hop": sum(last[r["qid"]] in p for p, r in zip(pools, rows, strict=True)),
            "pool_size": round(sum(len(p) for p in pools) / len(rows), 1),
        }

    out["coverage"]["bm25@30"] = coverage([set(r["bm25"][:30]) for r in rows])
    out["coverage"]["bm25@35"] = coverage([set(r["bm25"][:35]) for r in rows])
    keys = [f"{name}{suffix}" for name in CHANNELS for suffix in ("", "-novel")]
    keys = [key for key in keys if rows and key in rows[0]]
    for key in keys:
        out["coverage"][f"bm25@30+{key}"] = coverage(
            [set(r["bm25"][:30]) | set(r[key]) for r in rows]
        )
    tune = [r for r in rows if r["half"] == "tune"]
    confirm = [r for r in rows if r["half"] == "confirm"]
    for key in keys:

        def r5(r: dict, weight: float, key: str = key) -> float:
            fused = weighted_rrf([(r["bm25"][:30], 1.0), (r[key], weight)])
            return recall_at(fused, gold[r["qid"]], 5)

        by_weight = {w: sum(r5(r, w) for r in tune) / len(tune) for w in GRAPH_WEIGHTS}
        best = max(GRAPH_WEIGHTS, key=lambda w: (by_weight[w], -w))
        base = [recall_at(r["bm25"], gold[r["qid"]], 5) for r in confirm]
        fused = [r5(r, best) for r in confirm]
        wins = sum(f > b for f, b in zip(fused, base, strict=True))
        losses = sum(f < b for f, b in zip(fused, base, strict=True))
        out["rrf"][key] = {
            "tune_r5_by_weight": {str(w): round(100 * v, 2) for w, v in by_weight.items()},
            "chosen_weight": best,
            "confirm_bm25_r5": round(100 * sum(base) / len(base), 2),
            "confirm_fused_r5": round(100 * sum(fused) / len(fused), 2),
            "wins": wins,
            "losses": losses,
            "sign_p": round(sign_test(wins, losses), 4),
        }
    for half, subset in (("tune", tune), ("confirm", confirm)):
        out[f"bm25_{half}"] = {
            f"r@{k}": round(
                100 * sum(recall_at(r["bm25"], gold[r["qid"]], k) for r in subset) / len(subset), 2
            )
            for k in (2, 5)
        }
    return out


def main() -> None:
    import argparse
    import logging

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, required=True, help="<dataset>_corpus.json")
    parser.add_argument("--label-prefix", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-docs", type=int, default=100)
    parser.add_argument("--hub-cap", type=int, default=200)
    parser.add_argument("--rank-power", type=float, default=1.0, help="ranked teleport power")
    parser.add_argument(
        "--channels", default=",".join(CHANNELS), help="comma-separated subset of channels"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    from types import SimpleNamespace

    from benchmarks.musique.scripts.hipporag_set import load_corpus, passage_text
    from metronix.retrieval.channels import _ppr_seed_weights
    from metronix.retrieval.ppr import WeightedEdge, document_scores, personalized_pagerank
    from metronix.storage.graph_ops import (
        get_entities_by_doc_labels,
        get_entity_node_ids,
        get_ppr_subgraph,
        get_ppr_subgraph_specific,
    )

    corpus = load_corpus(args.corpus, args.label_prefix)
    bm25 = BM25({label: passage_text(p) for label, p in corpus.items()})
    with args.manifest.open(encoding="utf-8") as handle:
        manifest = [json.loads(line) for line in handle if line.strip()][: args.limit]

    def channel(anchors: list[str], subgraph: str, teleport: str, exclude: bool) -> list[str]:
        entities = get_entities_by_doc_labels(anchors, workspace_id=args.workspace)
        seeds = sorted({e["name"] for e in entities if e.get("name")})
        if not seeds:
            return []
        if subgraph == "specific":
            nodes, edges = get_ppr_subgraph_specific(
                seeds, workspace_id=args.workspace, max_docs=args.max_docs, hub_cap=args.hub_cap
            )
        else:
            nodes, edges = get_ppr_subgraph(seeds, workspace_id=args.workspace, max_nodes=500)
        if not edges:
            return []
        tele = {node: 1.0 for node, label in nodes.items() if label is None}
        if teleport in ("seeds", "ranked"):
            # The production weighting, with the BM25 top 5 as the dense anchors.
            ctx = SimpleNamespace(
                settings=SimpleNamespace(retrieval_graph_ppr_teleport_rank_power=args.rank_power),
                workspace_id=args.workspace,
                extracted_jira_keys=[],
                extracted_title_entities=[],
                detected_person=[],
            )
            weights = asyncio.run(_ppr_seed_weights(ctx, teleport, set(seeds), anchors, {}))
            seeded: dict[str, float] = {}
            for name, node in get_entity_node_ids(sorted(weights), args.workspace).items():
                if node in tele and weights.get(name, 0.0) > 0.0:
                    seeded[node] = seeded.get(node, 0.0) + weights[name]
            tele = seeded or tele
        scores = document_scores(
            personalized_pagerank(
                [WeightedEdge(*e) for e in edges],
                tele,
                alpha=0.85,
                max_iterations=30,
                tolerance=1e-6,
            ),
            nodes,
        )
        if exclude:
            for anchor in anchors:
                scores.pop(anchor, None)
        return sorted(scores, key=lambda label: (-scores[label], label))[:5]

    selected = set(args.channels.split(","))
    rows = []
    for i, m in enumerate(manifest):
        first = bm25.top(m["question"], 40)
        row = {"qid": m["qid"], "half": "tune" if i % 2 == 0 else "confirm", "bm25": first}
        for name, (subgraph, teleport) in CHANNELS.items():
            if name not in selected:
                continue
            row[name] = channel(first[:5], subgraph, teleport, exclude=False)
            row[f"{name}-novel"] = channel(first[:5], subgraph, teleport, exclude=True)
        rows.append(row)
        if (i + 1) % 100 == 0:
            print(f"[proxy] {i + 1}/{len(manifest)}", flush=True)

    gold = {m["qid"]: set(m["supporting_doc_labels"]) for m in manifest}
    last = {m["qid"]: m["hops"][-1]["doc_label"] for m in manifest}
    summary = analyse(rows, gold, last)
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
