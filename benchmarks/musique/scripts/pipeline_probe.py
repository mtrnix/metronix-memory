"""End-to-end retrieval probe: does the gold evidence reach the answer model's context?

Runs the production ``hybrid_search_and_answer`` (recall channels, merge, signal scoring,
cross-encoder rerank, fragment selection under the token budget) on a loaded MuSiQue
workspace and checks, per question, whether each gold paragraph is among the
``retrieved_doc_labels`` (post-rerank top-k) and among the ``fragments`` handed to the LLM.

Only LLM calls are removed, so the probe needs no chat model and measures retrieval alone:

* ``resolve_query`` and answer generation go through stubs (the resolver stub returns
  nothing, which makes ``resolve_query`` fall back to the original question);
* query expansion and the query classifier are switched off with their own settings
  (``QUERY_EXPANSION_ENABLED=false``, ``QUERY_CLASSIFIER_ENABLED=false``), so the dense
  query is the question itself and the scoring profile is ``mixed``.

The graph configuration is chosen per run with ``--graph``; each run should be a fresh
process because ``metronix.retrieval.search`` reads its settings at import time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

GRAPH_MODES = {
    # graph recall channel removed (harness ablation, not a product setting)
    "off": {},
    # production default: BFS graph channel
    "bfs": {},
    "ppr": {"METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED": "true"},
    "ppr-novel": {
        "METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED": "true",
        "METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS": "true",
    },
}

RETRIEVAL_ONLY_ENV = {
    "QUERY_EXPANSION_ENABLED": "false",
    "QUERY_CLASSIFIER_ENABLED": "false",
}


def gold_positions(gold: list[str], labels: list[str]) -> dict[str, int | None]:
    """1-based position of each gold doc among distinct labels (None if absent)."""
    order = list(dict.fromkeys(label for label in labels if label))
    return {g: (order.index(g) + 1 if g in order else None) for g in gold}


def score_row(manifest_row: dict, trace: dict) -> dict:
    gold = [h["doc_label"] for h in manifest_row["hops"]]
    retrieved = trace.get("retrieved_doc_labels") or []
    context = [f.get("doc_label", "") for f in trace.get("fragments") or []]
    stages = trace.get("pipeline_stages") or {}
    ctx_pos = gold_positions(gold, context)
    return {
        "qid": manifest_row["qid"],
        "gold": gold,
        "retrieved_rank": gold_positions(gold, retrieved),
        "context_rank": ctx_pos,
        "context_hop0": ctx_pos[gold[0]] is not None,
        "context_last_hop": ctx_pos[gold[-1]] is not None,
        "context_both": all(v is not None for v in ctx_pos.values()),
        "context_docs": len(dict.fromkeys(context)),
        "recall_graph_count": stages.get("recall_graph_count"),
        "recall_total_unique": stages.get("recall_total_unique"),
    }


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    out = {"questions": n}
    for key in ("context_hop0", "context_last_hop", "context_both"):
        out[key] = sum(r[key] for r in rows)
    for k in (5, 10):
        out[f"retrieved@{k}_both"] = sum(
            all(v is not None and v <= k for v in r["retrieved_rank"].values()) for r in rows
        )
        out[f"retrieved@{k}_last_hop"] = sum(
            (list(r["retrieved_rank"].values())[-1] or 10**9) <= k for r in rows
        )
    docs = sorted(r["context_docs"] for r in rows)
    out["context_docs_median"] = docs[n // 2] if docs else 0
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--manifest", type=Path, default=Path("benchmarks/musique/data/manifest.jsonl")
    )
    parser.add_argument("--workspace", default="musique-dev")
    parser.add_argument("--graph", choices=sorted(GRAPH_MODES), default="bfs")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--k", type=int, default=25, help="hybrid_search_and_answer k")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    # Settings are read at import time: set the environment before importing metronix.
    os.environ.update(RETRIEVAL_ONLY_ENV)
    os.environ.update(GRAPH_MODES[args.graph])

    import asyncio
    import logging
    from unittest.mock import patch

    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    from metronix.retrieval import search

    async def _no_graph(ctx, *a, **kw):
        return []

    with args.manifest.open(encoding="utf-8") as handle:
        manifest = [json.loads(line) for line in handle if line.strip()][: args.limit]

    patches = [
        patch.object(search, "chat_completion", return_value=""),
        patch.object(search, "chat_completion_with_retry", return_value="(stub answer)"),
    ]
    if args.graph == "off":
        patches += [
            patch.object(search, "recall_graph_async", _no_graph),
            patch.object(search, "recall_graph_ppr_async", _no_graph),
        ]

    rows: list[dict] = []
    for p in patches:
        p.start()
    try:
        for m in manifest:
            trace = asyncio.run(
                search.hybrid_search_and_answer(
                    m["question"], k=args.k, workspace_id=args.workspace, return_trace=True
                )
            )
            row = score_row(m, trace)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        for p in patches:
            p.stop()

    summary = {"graph": args.graph, **aggregate(rows)}
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
