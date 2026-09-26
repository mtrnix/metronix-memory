"""Load a HippoRAG / HippoRAG 2 evaluation set (MuSiQue or 2Wiki) into a Metronix workspace.

HippoRAG (Gutiérrez et al., 2024) and HippoRAG 2 (2025) report passage Recall@2/@5 on
1,000 dev questions per dataset over the distinct paragraphs of those questions
(``reproduce/dataset/<dataset>.json`` and ``<dataset>_corpus.json`` in
github.com/OSU-NLP-Group/HippoRAG): 11,656 passages for MuSiQue, 6,119 for
2WikiMultiHopQA. For MuSiQue the same repository ships the OpenIE output HippoRAG 2 built
its graph from (``outputs/musique/openie_results_ner_<model>.json``: entities and
subject-relation-object triples per passage). Loading exactly that corpus, those questions
and that extraction makes Metronix's numbers comparable with the published ones; the
remaining differences are the embedder, the reranker and the fusion.

Passages are stored as ``title + "\n" + text``, the string HippoRAG indexes and matches
gold passages against (the title is also kept in the metadata, as production does).

Graph shape (``--graph openie``), in the node/edge form ``write_doc_graph`` produces:

* every passage -> ``Document {doc_label}``; it MENTIONS every entity it yields
  (``extracted_entities`` plus triple subjects and objects);
* every triple -> ``(subject)-[:RELATION {type: predicate}]->(object)``;
* entity names are grouped the way HippoRAG groups phrase nodes (lower case, non
  alphanumerics as spaces); a group's node is named after its most frequent surface
  form, so production seed extraction (title-cased names) can still match it.

HippoRAG 2 additionally links phrase nodes by embedding similarity (synonym edges) and
embeds triples for query-to-triple linking; neither exists in Metronix and neither is
added here. ``--graph oracle`` builds the MuSiQue decomposition graph of ``convert.py``
instead (an upper bound).

No OpenIE output is published for 2Wiki, and extracting 6,119 passages with the local LLM
is out of reach on CPU. ``--graph titles`` builds a graph without any LLM or annotation:
every passage mentions the entity named after its own title (disambiguation in
parentheses removed) and every other corpus title that occurs in its text, matched
case-sensitively on word boundaries -- a hyperlink-like graph built from the text alone.
The gold labels play no part in it.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.musique.scripts.convert import (
    GraphSession,
    QuestionGraph,
    build_question_graph,
    paragraph_label,
    write_graph,
)

SOURCE = "musique-hipporag"
DATASETS = ("musique", "2wikimultihopqa")


def phrase_key(name: str) -> str:
    """HippoRAG's phrase normalisation: lower case, non-alphanumerics become spaces."""
    return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", str(name).lower()).split())


@dataclass
class OpenIEGraph:
    # doc_label -> canonical entity names it mentions
    mentions: dict[str, set[str]] = field(default_factory=dict)
    # (subject, relation, object) with canonical names, deduplicated
    triples: set[tuple[str, str, str]] = field(default_factory=set)

    def summary(self) -> dict[str, int]:
        return {
            "documents_with_mentions": sum(1 for v in self.mentions.values() if v),
            "entities": len({n for names in self.mentions.values() for n in names}),
            "mentions": sum(len(v) for v in self.mentions.values()),
            "triples": len(self.triples),
        }


def build_openie_graph(openie_docs: Iterable[dict], label_prefix: str) -> OpenIEGraph:
    """Canonicalise HippoRAG OpenIE output into mentions + RELATION triples."""
    docs = list(openie_docs)
    surface: dict[str, Counter] = defaultdict(Counter)

    def note(name: Any) -> str | None:
        if not isinstance(name, str):
            return None
        key = phrase_key(name)
        if not key:
            return None
        surface[key][" ".join(name.split())] += 1
        return key

    raw: list[tuple[str, set[str], list[tuple[str, str, str]]]] = []
    for doc in docs:
        label = paragraph_label(doc["title"], doc["text"], label_prefix)
        keys = {k for k in (note(e) for e in doc.get("extracted_entities") or []) if k}
        triples: list[tuple[str, str, str]] = []
        for triple in doc.get("extracted_triples") or []:
            if not isinstance(triple, list | tuple) or len(triple) != 3:
                continue
            subj, rel, obj = (note(triple[0]), triple[1], note(triple[2]))
            if subj and obj and isinstance(rel, str) and subj != obj:
                keys.update((subj, obj))
                triples.append((subj, " ".join(rel.split()), obj))
        raw.append((label, keys, triples))

    # Most frequent surface form; ties broken alphabetically for determinism.
    canonical = {
        key: sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        for key, counts in surface.items()
    }
    graph = OpenIEGraph()
    for label, keys, triples in raw:
        graph.mentions.setdefault(label, set()).update(canonical[k] for k in keys)
        graph.triples.update((canonical[s], r, canonical[o]) for s, r, o in triples)
    return graph


_DISAMBIGUATION = re.compile(r"\s*\([^)]*\)\s*$")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def title_entity(title: str) -> str:
    """``"Theodred II (Bishop of Elmham)"`` -> ``"Theodred II"``."""
    return " ".join(_DISAMBIGUATION.sub("", str(title)).split()) or " ".join(title.split())


def _linkable(name: str, min_chars: int) -> bool:
    tokens = _TOKEN.findall(name)
    return (
        len(name) >= min_chars
        and bool(tokens)
        and any(t[0].isupper() for t in tokens)
        and not all(t.isdigit() for t in tokens)
    )


def build_title_graph(
    corpus: dict[str, dict], min_chars: int = 4, max_tokens: int = 10
) -> OpenIEGraph:
    """Hyperlink-like graph: a passage mentions its own title and every title in its text.

    Titles are matched on their token sequence (letters and digits, case kept), so
    "Lothair II's mother" links to "Lothair II" but "love" does not link to "Love".
    """
    names: dict[tuple[str, ...], str] = {}
    for p in corpus.values():
        name = title_entity(p["title"])
        if _linkable(name, min_chars):
            key = tuple(_TOKEN.findall(name))
            if 0 < len(key) <= max_tokens:
                names.setdefault(key, name)
    longest = max((len(k) for k in names), default=0)
    graph = OpenIEGraph()
    for label, p in corpus.items():
        mentioned = {title_entity(p["title"])}
        tokens = _TOKEN.findall(p["text"])
        for i in range(len(tokens)):
            for n in range(1, min(longest, len(tokens) - i) + 1):
                name = names.get(tuple(tokens[i : i + n]))
                if name is not None:
                    mentioned.add(name)
        graph.mentions[label] = mentioned
    return graph


def twowiki_manifest(records: list[dict], corpus: dict[str, dict]) -> list[dict]:
    """Manifest rows for 2Wiki: gold = the passages of the supporting-fact titles.

    ``hops`` lists them in the order of ``supporting_facts`` (for compositional and
    inference questions that is the chain order); comparison questions have no bridge,
    so "last hop" is only meaningful per question type (kept in ``type``).
    """
    by_title = {p["title"]: label for label, p in corpus.items()}
    rows = []
    for r in records:
        titles = list(dict.fromkeys(t for t, _ in r["supporting_facts"]))
        labels = [by_title[t] for t in titles if t in by_title]
        rows.append(
            {
                "qid": r["_id"],
                "question": r["question"],
                "answer": r["answer"],
                "type": r.get("type"),
                "hops": [
                    {"hop": i, "doc_label": label, "title": t}
                    for i, (t, label) in enumerate(
                        (t, by_title[t]) for t in titles if t in by_title
                    )
                ],
                "supporting_doc_labels": labels,
                "missing_gold_titles": [t for t in titles if t not in by_title],
                "hop_count": len(labels),
            }
        )
    return rows


_CYPHER_DOCS = (
    "UNWIND $rows AS row "
    "MERGE (d:Document {doc_id: row.dl}) "
    "SET d.doc_label = row.dl, d.workspace_id = $ws, d.file_name = row.title, "
    "    d.raw_text = row.text, d.source = $src"
)
_CYPHER_MENTIONS = (
    "UNWIND $rows AS row "
    "MATCH (d:Document {doc_id: row.dl}) "
    "MERGE (e:Entity {name: row.name, workspace_id: $ws}) "
    "ON CREATE SET e.type = 'openie', e.source = $src "
    "SET e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [row.dl] "
    "    WHEN row.dl IN e.doc_labels THEN e.doc_labels "
    "    ELSE e.doc_labels + [row.dl] END "
    "MERGE (d)-[:MENTIONS]->(e)"
)
_CYPHER_RELATIONS = (
    "UNWIND $rows AS row "
    "MERGE (e1:Entity {name: row.s, workspace_id: $ws}) "
    "MERGE (e2:Entity {name: row.o, workspace_id: $ws}) "
    "MERGE (e1)-[r:RELATION {type: row.r, workspace_id: $ws}]->(e2) "
    "SET r.source = $src"
)


def _batches(rows: list[dict], size: int = 500) -> Iterable[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def write_openie_graph(
    session: GraphSession,
    graph: OpenIEGraph,
    corpus: dict[str, dict],
    workspace_id: str,
) -> None:
    """Write Documents, MENTIONS and RELATION edges in batches."""
    session.run(
        "CREATE INDEX entity_name_ws IF NOT EXISTS FOR (e:Entity) ON (e.name, e.workspace_id)"
    )
    session.run("CREATE INDEX document_doc_id IF NOT EXISTS FOR (d:Document) ON (d.doc_id)")
    doc_rows = [
        {"dl": dl, "title": p["title"], "text": p["text"]} for dl, p in sorted(corpus.items())
    ]
    for batch in _batches(doc_rows):
        session.run(_CYPHER_DOCS, {"rows": batch, "ws": workspace_id, "src": SOURCE})
    mention_rows = [
        {"dl": dl, "name": name}
        for dl, names in sorted(graph.mentions.items())
        if dl in corpus
        for name in sorted(names)
    ]
    for batch in _batches(mention_rows):
        session.run(_CYPHER_MENTIONS, {"rows": batch, "ws": workspace_id, "src": SOURCE})
    rel_rows = [{"s": s, "r": r, "o": o} for s, r, o in sorted(graph.triples)]
    for batch in _batches(rel_rows):
        session.run(_CYPHER_RELATIONS, {"rows": batch, "ws": workspace_id, "src": SOURCE})


def load_corpus(path: Path, label_prefix: str) -> dict[str, dict]:
    with path.open(encoding="utf-8") as handle:
        passages = json.load(handle)
    return {paragraph_label(p["title"], p["text"], label_prefix): p for p in passages}


def passage_text(p: dict) -> str:
    """The string HippoRAG indexes for a passage."""
    return f"{p['title']}\n{p['text']}"


def question_graphs(path: Path, label_prefix: str) -> list[QuestionGraph]:
    with path.open(encoding="utf-8") as handle:
        records = json.load(handle)
    return [build_question_graph(r, label_prefix=label_prefix) for r in records]


def main() -> None:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hipporag-dir", type=Path, required=True)
    parser.add_argument("--dataset", choices=DATASETS, default="musique")
    parser.add_argument("--workspace", default="musique-hipporag")
    parser.add_argument("--label-prefix", default="mhr")
    parser.add_argument(
        "--graph", choices=["openie", "titles", "oracle", "none"], default="openie"
    )
    parser.add_argument(
        "--openie-model", default="meta-llama_Llama-3.3-70B-Instruct", help="OpenIE file suffix"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--workers", type=int, default=2, help="parallel add_document calls")
    args = parser.parse_args()

    root = args.hipporag_dir
    dataset_dir = root / "reproduce/dataset"
    corpus = load_corpus(dataset_dir / f"{args.dataset}_corpus.json", args.label_prefix)
    graphs: list[QuestionGraph] = []
    if args.dataset == "musique":
        graphs = question_graphs(dataset_dir / "musique.json", args.label_prefix)
        rows = []
        for g in graphs:
            row = g.manifest()
            row["hop_count"] = len(g.hops)
            rows.append(row)
    else:
        if args.graph in ("openie", "oracle"):
            parser.error(f"--graph {args.graph} is only available for musique")
        with (dataset_dir / f"{args.dataset}.json").open(encoding="utf-8") as handle:
            rows = twowiki_manifest(json.load(handle), corpus)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    missing = {h["doc_label"] for r in rows for h in r["hops"]} - set(corpus)
    summary: dict[str, Any] = {
        "dataset": args.dataset,
        "questions": len(rows),
        "corpus_passages": len(corpus),
        "gold_not_in_corpus": len(missing)
        + sum(len(r.get("missing_gold_titles") or []) for r in rows),
        "hop_counts": dict(Counter(r["hop_count"] for r in rows)),
    }
    graph = None
    if args.graph == "openie":
        path = root / f"outputs/musique/openie_results_ner_{args.openie_model}.json"
        with path.open(encoding="utf-8") as handle:
            graph = build_openie_graph(json.load(handle)["docs"], args.label_prefix)
        summary["openie_docs_not_in_corpus"] = len(set(graph.mentions) - set(corpus))
    elif args.graph == "titles":
        graph = build_title_graph(corpus)
    if graph is not None:
        summary["graph"] = graph.summary()
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        return

    from metronix.storage.neo4j_graph import delete_workspace_graph, get_graph_driver
    from metronix.storage.qdrant import get_hybrid_store

    store = None if args.skip_qdrant else get_hybrid_store(args.workspace)
    if args.reset:
        delete_workspace_graph(args.workspace)
        if store is not None:
            store.clear()

    if store is not None:
        items = sorted(corpus.items())

        def add(item: tuple[str, dict]) -> None:
            label, p = item
            store.add_document(
                passage_text(p),
                metadata={
                    "doc_label": label,
                    "title": p["title"],
                    "type": SOURCE,
                    "source": SOURCE,
                },
                doc_id=label,
            )

        with ThreadPoolExecutor(max_workers=max(args.workers, 1)) as pool:
            for i, _ in enumerate(pool.map(add, items), 1):
                if i % 500 == 0:
                    print(f"[qdrant] {i}/{len(items)}", flush=True)

    with get_graph_driver().session() as session:
        if graph is not None:
            write_openie_graph(session, graph, corpus, args.workspace)
        elif args.graph == "oracle":
            for g in graphs:
                write_graph(session, g, args.workspace)
    print(f"loaded {len(corpus)} passages into workspace {args.workspace!r}")


if __name__ == "__main__":
    main()
