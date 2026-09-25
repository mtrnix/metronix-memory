"""Per-hop probe of the graph channel on a loaded MuSiQue workspace.

``recall_graph`` returns only ``search_by_doc_labels(set(all_labels), limit)``, an
unordered cut, so a hop-1 document can be found by BFS yet dropped from the top-N.
This probe replays the same BFS (seeds -> aliases -> direct labels -> iterative
expansion via get_graph_relationships) and records the hop at which each gold
document first appears, then also runs the real recall_graph for comparison.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

# Mirrors metronix.retrieval.channels._MAX_FRONTIER.
MAX_FRONTIER = 50

RelsFn = Callable[..., list[dict]]
LabelsFn = Callable[..., list[dict]]
AliasFn = Callable[..., dict]


@dataclass
class HopTrace:
    labels_by_hop: dict[str, int]
    entities_by_hop: list[set[str]]

    def hop_of(self, doc_label: str) -> int | None:
        return self.labels_by_hop.get(doc_label)


def trace_bfs(
    seeds: Iterable[str],
    workspace_id: str,
    max_depth: int,
    get_relationships: RelsFn,
    get_doc_labels: LabelsFn,
    resolve_aliases: AliasFn | None = None,
) -> HopTrace:
    seed_set = {s for s in seeds if s}
    if resolve_aliases and seed_set:
        for names in resolve_aliases(sorted(seed_set), workspace_id).values():
            seed_set.update(names)

    labels_by_hop: dict[str, int] = {}

    def record(names: Iterable[str], hop: int) -> None:
        names = list(names)[:MAX_FRONTIER]
        for row in get_doc_labels(names, workspace_id=workspace_id):
            label = row.get("doc_label")
            if label and label not in labels_by_hop:
                labels_by_hop[label] = hop

    entities_by_hop = [set(seed_set)]
    if not seed_set:
        return HopTrace(labels_by_hop, entities_by_hop)
    record(seed_set, 0)

    seen = set(seed_set)
    frontier = set(seed_set)
    for hop in range(1, max_depth + 1):
        if not frontier:
            break
        rels = get_relationships(
            list(frontier)[:MAX_FRONTIER], workspace_id=workspace_id, max_depth=1
        )
        neighbours = {r["source"] for r in rels} | {r["target"] for r in rels}
        frontier = {n for n in neighbours if n} - seen
        seen.update(frontier)
        entities_by_hop.append(set(frontier))
        if frontier:
            record(frontier, hop)
    return HopTrace(labels_by_hop, entities_by_hop)


def score_question(manifest_row: dict, trace: HopTrace) -> dict:
    gold = [(h["hop"], h["doc_label"]) for h in manifest_row["hops"]]
    found = {label: trace.hop_of(label) for _, label in gold}
    distractors = set(manifest_row["distractor_doc_labels"])
    distractors_found = sum(1 for label in trace.labels_by_hop if label in distractors)
    return {
        "qid": manifest_row["qid"],
        "seeds": sorted(trace.entities_by_hop[0]),
        "gold_found_at_hop": found,
        # A real multi-hop win: the last-step paragraph reached only via expansion.
        "last_hop_via_bfs": (found.get(gold[-1][1]) or 0) >= 1,
        "all_gold_found": all(v is not None for v in found.values()),
        "same_question_distractors_found": distractors_found,
        "labels_total": len(trace.labels_by_hop),
    }


def dense_ranks(gold_labels: list[str], dense_labels: list[str]) -> dict[str, int | None]:
    """1-based rank of each gold doc among the dense channel's distinct doc labels."""
    order: list[str] = []
    for label in dense_labels:
        if label not in order:
            order.append(label)
    return {g: (order.index(g) + 1 if g in order else None) for g in gold_labels}


def _hit(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def aggregate(rows: list[dict]) -> dict:
    n = len(rows) or 1
    summary = {
        "questions": len(rows),
        "no_seed": sum(not r["seeds"] for r in rows),
        "all_gold_found": sum(r["all_gold_found"] for r in rows),
        "last_hop_via_bfs": sum(r["last_hop_via_bfs"] for r in rows),
        "last_hop_via_bfs_rate": round(sum(r["last_hop_via_bfs"] for r in rows) / n, 3),
    }
    dense_rows = [r for r in rows if "dense_gold_rank" in r]
    if dense_rows:
        for k in (5, 10, 30):
            first = sum(_hit(list(r["dense_gold_rank"].values())[0], k) for r in dense_rows)
            last = sum(_hit(list(r["dense_gold_rank"].values())[-1], k) for r in dense_rows)
            both = sum(all(_hit(v, k) for v in r["dense_gold_rank"].values()) for r in dense_rows)
            summary[f"dense@{k}"] = {"hop0": first, "last_hop": last, "both": both}
        for key, name in (("recall_graph_labels", "graph"), ("ppr_labels", "ppr")):
            if all(key in r for r in dense_rows):
                summary[name] = _channel_summary(dense_rows, key)
                summary[f"dense@30_or_{name}"] = _union_summary(dense_rows, key)
    return summary


def _channel_summary(rows: list[dict], key: str) -> dict:
    """What a graph channel returns on its own (its top recall_top_n_graph docs)."""
    return {
        "hop0": sum(list(r["dense_gold_rank"])[0] in r[key] for r in rows),
        "last_hop": sum(list(r["dense_gold_rank"])[-1] in r[key] for r in rows),
        "both": sum(all(g in r[key] for g in r["dense_gold_rank"]) for r in rows),
        "empty": sum(not r[key] for r in rows),
    }


def _union_summary(rows: list[dict], key: str) -> dict:
    """Dense top-30 plus a graph channel's docs: the candidate pool fusion can draw on."""
    return {
        "last_hop": sum(
            _hit(list(r["dense_gold_rank"].values())[-1], 30)
            or list(r["dense_gold_rank"])[-1] in r[key]
            for r in rows
        ),
        "both": sum(
            all(_hit(rank, 30) or label in r[key] for label, rank in r["dense_gold_rank"].items())
            for r in rows
        ),
        "last_hop_only_via_graph": sum(
            not _hit(list(r["dense_gold_rank"].values())[-1], 30)
            and list(r["dense_gold_rank"])[-1] in r[key]
            for r in rows
        ),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Per-hop graph-channel probe on MuSiQue")
    parser.add_argument(
        "--manifest", type=Path, default=Path("benchmarks/musique/data/manifest.jsonl")
    )
    parser.add_argument("--workspace", default="musique-dev")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument(
        "--seeds",
        choices=["oracle", "title"],
        default="oracle",
        help="oracle: step-0 subject from the manifest; title: extract_title_entities(question)",
    )
    parser.add_argument("--recall", action="store_true", help="also run recall_graph")
    parser.add_argument(
        "--dense",
        action="store_true",
        help="also run recall_dense (hybrid dense+sparse RRF; needs the embedding service)",
    )
    parser.add_argument(
        "--ppr",
        action="store_true",
        help="also run the opt-in PPR graph channel, anchored on dense results (needs --dense)",
    )
    parser.add_argument(
        "--ppr-exclude-anchors",
        action="store_true",
        help="set METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS for the PPR run",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.ppr and not args.dense:
        parser.error("--ppr needs --dense (PPR is anchored on the dense results)")

    import logging

    # Neo4j warns on every query touching properties the MuSiQue graph never sets
    # (valid_from, mention_count, ...); those notifications are noise here.
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    from metronix.retrieval.search import extract_title_entities
    from metronix.storage.graph_ops import (
        get_doc_labels_by_entities,
        get_graph_relationships,
        resolve_entity_aliases_batch,
    )

    with args.manifest.open(encoding="utf-8") as handle:
        manifest = [json.loads(line) for line in handle if line.strip()][: args.limit]

    rows: list[dict] = []
    for m in manifest:
        seeds = (
            [m["seed_entity"]] if args.seeds == "oracle" else extract_title_entities(m["question"])
        )
        trace = trace_bfs(
            seeds,
            args.workspace,
            args.max_depth,
            get_graph_relationships,
            get_doc_labels_by_entities,
            resolve_entity_aliases_batch,
        )
        row = score_question(m, trace)
        if args.recall:
            row["recall_graph_labels"] = _run_recall_graph(m, seeds, args)
        if args.dense:
            dense = _run_recall_dense(m, args)
            row["dense_labels"] = [r["doc_label"] for r in dense]
            row["dense_scores"] = [round(float(r["score"]), 6) for r in dense]
            row["dense_gold_rank"] = dense_ranks(
                [h["doc_label"] for h in m["hops"]], row["dense_labels"]
            )
            if args.ppr:
                row["ppr_labels"] = _run_recall_graph_ppr(m, seeds, dense, args)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    summary = aggregate(rows)
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _context(manifest_row: dict, seeds: list[str], args):
    from metronix.core.config import get_settings
    from metronix.retrieval.channels import RecallContext

    settings = get_settings().model_copy(
        update={
            "recall_graph_max_depth": args.max_depth,
            "retrieval_graph_ner_enabled": True,
            "retrieval_graph_ppr_exclude_dense_anchors": bool(
                getattr(args, "ppr_exclude_anchors", False)
            ),
        }
    )
    return RecallContext(
        original_query=manifest_row["question"],
        translated_query=manifest_row["question"],
        expanded_query=manifest_row["question"],
        detected_language="en",
        workspace_id=args.workspace,
        access_filter=None,
        settings=settings,
        extracted_jira_keys=[],
        extracted_title_entities=list(seeds),
        extracted_dates=None,
        detected_person=[],
        is_activity_query=False,
    )


def _run_recall_graph(manifest_row: dict, seeds: list[str], args) -> list[str]:
    from metronix.retrieval.channels import recall_graph

    return [r["doc_label"] for r in recall_graph(_context(manifest_row, seeds, args))]


def _run_recall_graph_ppr(
    manifest_row: dict, seeds: list[str], dense: list[dict], args
) -> list[str]:
    import asyncio

    from metronix.retrieval.channels import recall_graph_ppr_async

    ctx = _context(manifest_row, seeds, args)
    return [r["doc_label"] for r in asyncio.run(recall_graph_ppr_async(ctx, dense))]


def _run_recall_dense(manifest_row: dict, args) -> list[dict]:
    from metronix.retrieval.channels import recall_dense

    return recall_dense(_context(manifest_row, [], args))


if __name__ == "__main__":
    main()
