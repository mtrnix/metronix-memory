"""Convert MuSiQue questions into Metronix documents (Qdrant) and an oracle graph (Neo4j).

Oracle graph, no LLM extraction:

* every distinct paragraph -> one Document (supporting, plus distractors unless
  disabled). MuSiQue reuses the same Wikipedia paragraph across questions, so the
  doc_label is a hash of (title, text): per-question copies would let BFS land on
  another question's copy of the gold text and score it as a miss;
  each Document MENTIONS the Entity named after its Wikipedia title;
* every decomposition step i -> RELATION ``subject_i -[relation_i]-> answer_i``;
  the supporting paragraph of step i MENTIONS both endpoints;
* the subject of step i is the answer of step k when the sub-question references
  ``#k``, else the left side of ``subject >> relation``, else the paragraph title;
* every ``answer_aliases`` entry -> ``(alias)-[:ALIAS]->(final answer)``, the same
  direction write_doc_graph uses for merged aliases.

For a 2-hop question, a BFS seeded with the step-0 subject finds p0 directly and
p1 only after one hop (subject -> answer_0), which is what the probe measures.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

SOURCE = "musique"
_REF = re.compile(r"#(\d+)")


@dataclass(frozen=True)
class DocSpec:
    doc_label: str
    qid: str
    paragraph_idx: int
    title: str
    text: str
    is_supporting: bool


@dataclass(frozen=True)
class RelationSpec:
    source: str
    target: str
    type: str
    hop: int
    doc_label: str


@dataclass(frozen=True)
class HopSpec:
    hop: int
    doc_label: str
    subject: str
    relation: str
    answer: str


@dataclass
class QuestionGraph:
    qid: str
    question: str
    answer: str
    seed_entity: str
    hops: list[HopSpec]
    documents: list[DocSpec]
    # entity name -> entity type
    entities: dict[str, str] = field(default_factory=dict)
    # (doc_label, entity name)
    mentions: list[tuple[str, str]] = field(default_factory=list)
    relations: list[RelationSpec] = field(default_factory=list)
    # (alias name, canonical name)
    aliases: list[tuple[str, str]] = field(default_factory=list)

    def manifest(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "question": self.question,
            "answer": self.answer,
            "answer_aliases": [alias for alias, _ in self.aliases],
            "seed_entity": self.seed_entity,
            "hops": [asdict(h) for h in self.hops],
            "supporting_doc_labels": [d.doc_label for d in self.documents if d.is_supporting],
            "distractor_doc_labels": [d.doc_label for d in self.documents if not d.is_supporting],
            "distractor_count": sum(not d.is_supporting for d in self.documents),
        }


def paragraph_label(title: str, text: str, prefix: str = SOURCE) -> str:
    """Content-hash doc label. ``prefix`` keeps graphs of different workspaces apart:
    Document nodes are MERGEd on doc_id alone, so two workspaces must not share labels."""
    digest = hashlib.sha1(f"{_clean(title)}\n{text.strip()}".encode()).hexdigest()
    return f"{prefix}:para:{digest[:16]}"


def _clean(name: str) -> str:
    return " ".join(str(name).split())


def relation_type(step_question: str) -> str:
    """``"Green >> performer"`` -> ``performer``; free text -> snake_case of the question."""
    text = step_question.split(">>", 1)[1] if ">>" in step_question else step_question
    text = _REF.sub(" ", text).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug[:64] or "related_to"


def step_subject(step_question: str, answers: list[str], fallback_title: str) -> str:
    ref = _REF.search(step_question)
    if ref:
        k = int(ref.group(1))
        if 1 <= k <= len(answers):
            return answers[k - 1]
    if ">>" in step_question:
        lhs = _clean(step_question.split(">>", 1)[0])
        if lhs:
            return lhs
    return fallback_title


def build_question_graph(
    record: dict, include_distractors: bool = True, label_prefix: str = SOURCE
) -> QuestionGraph:
    qid = record["id"]
    paragraphs = {int(p["idx"]): p for p in record["paragraphs"]}
    labels = {
        idx: paragraph_label(p["title"], p["paragraph_text"], label_prefix)
        for idx, p in paragraphs.items()
    }

    # One DocSpec per distinct paragraph; a duplicate inside the question is
    # supporting if any of its copies is.
    by_label: dict[str, DocSpec] = {}
    for idx, p in sorted(paragraphs.items()):
        if not (include_distractors or p["is_supporting"]):
            continue
        label = labels[idx]
        prev = by_label.get(label)
        if prev is None:
            by_label[label] = DocSpec(
                doc_label=label,
                qid=qid,
                paragraph_idx=idx,
                title=_clean(p["title"]),
                text=p["paragraph_text"],
                is_supporting=bool(p["is_supporting"]),
            )
        elif p["is_supporting"] and not prev.is_supporting:
            by_label[label] = DocSpec(**{**asdict(prev), "is_supporting": True})
    documents = list(by_label.values())

    graph = QuestionGraph(
        qid=qid,
        question=record["question"],
        answer=_clean(record.get("answer", "")),
        seed_entity="",
        hops=[],
        documents=documents,
    )

    def add_entity(name: str, etype: str) -> None:
        # First writer wins, so a title that is also an answer keeps its title type.
        graph.entities.setdefault(name, etype)

    def add_mention(doc_label: str, name: str) -> None:
        if (doc_label, name) not in graph.mentions:
            graph.mentions.append((doc_label, name))

    for doc in documents:
        add_entity(doc.title, "musique_title")
        add_mention(doc.doc_label, doc.title)

    answers: list[str] = []
    for hop, step in enumerate(record["question_decomposition"]):
        support_idx = int(step["paragraph_support_idx"])
        if support_idx not in paragraphs:
            raise ValueError(f"{qid} step {hop} points at missing paragraph {support_idx}")
        doc_label = labels[support_idx]
        subject = _clean(
            step_subject(step["question"], answers, _clean(paragraphs[support_idx]["title"]))
        )
        answer = _clean(step["answer"])
        rtype = relation_type(step["question"])

        add_entity(subject, "musique_subject")
        add_entity(answer, "musique_answer")
        add_mention(doc_label, subject)
        add_mention(doc_label, answer)
        if subject != answer:
            graph.relations.append(RelationSpec(subject, answer, rtype, hop, doc_label))
        graph.hops.append(HopSpec(hop, doc_label, subject, rtype, answer))
        answers.append(answer)

    graph.seed_entity = graph.hops[0].subject

    final = graph.hops[-1].answer
    for raw in record.get("answer_aliases") or []:
        alias = _clean(raw)
        if alias and alias.casefold() != final.casefold() and alias not in graph.entities:
            graph.entities[alias] = "musique_alias"
            graph.aliases.append((alias, final))
    return graph


# --- writers --------------------------------------------------------------------


class GraphSession(Protocol):
    def run(self, query: str, parameters: dict | None = None) -> Any: ...


class VectorStore(Protocol):
    def add_document(
        self, text: str, metadata: dict[str, Any] | None = None, doc_id: str | None = None
    ) -> list[str]: ...


# Same node/edge shape as metronix.storage.neo4j_graph.write_doc_graph so that
# get_doc_labels_by_entities resolves both via Entity.doc_labels and via MENTIONS.
# A shared paragraph accumulates every question it appears in (qids) and every
# question it supports (supporting_qids).
_CYPHER_DOC = (
    "MERGE (d:Document {doc_id: $dl}) "
    "SET d.doc_label = $dl, d.workspace_id = $ws, d.file_name = $title, "
    "    d.raw_text = $text, d.source = $src, "
    "    d.qids = CASE WHEN d.qids IS NULL THEN [$qid] "
    "        WHEN $qid IN d.qids THEN d.qids ELSE d.qids + [$qid] END, "
    "    d.supporting_qids = CASE WHEN NOT $sup THEN coalesce(d.supporting_qids, []) "
    "        WHEN d.supporting_qids IS NULL THEN [$qid] "
    "        WHEN $qid IN d.supporting_qids THEN d.supporting_qids "
    "        ELSE d.supporting_qids + [$qid] END"
)
_CYPHER_MENTION = (
    "MATCH (d:Document {doc_id: $dl}) "
    "MERGE (e:Entity {name: $name, workspace_id: $ws}) "
    "ON CREATE SET e.type = $etype, e.source = $src "
    "SET e.doc_labels = CASE WHEN e.doc_labels IS NULL THEN [$dl] "
    "    WHEN $dl IN e.doc_labels THEN e.doc_labels "
    "    ELSE e.doc_labels + [$dl] END "
    "MERGE (d)-[:MENTIONS]->(e)"
)
_CYPHER_RELATION = (
    "MERGE (e1:Entity {name: $src_name, workspace_id: $ws}) "
    "MERGE (e2:Entity {name: $tgt_name, workspace_id: $ws}) "
    "MERGE (e1)-[r:RELATION {type: $rtype, workspace_id: $ws}]->(e2) "
    "SET r.source = $src, r.hop = $hop"
)
_CYPHER_ALIAS = (
    "MERGE (a:Entity {name: $alias, workspace_id: $ws}) "
    "ON CREATE SET a.type = $etype, a.source = $src "
    "MERGE (c:Entity {name: $canon, workspace_id: $ws}) "
    "MERGE (a)-[:ALIAS]->(c)"
)


def write_graph(session: GraphSession, graph: QuestionGraph, workspace_id: str) -> None:
    for doc in graph.documents:
        session.run(
            _CYPHER_DOC,
            {
                "dl": doc.doc_label,
                "ws": workspace_id,
                "title": doc.title,
                "text": doc.text,
                "src": SOURCE,
                "qid": doc.qid,
                "sup": doc.is_supporting,
            },
        )
    for doc_label, name in graph.mentions:
        session.run(
            _CYPHER_MENTION,
            {
                "dl": doc_label,
                "name": name,
                "ws": workspace_id,
                "etype": graph.entities[name],
                "src": SOURCE,
            },
        )
    for rel in graph.relations:
        session.run(
            _CYPHER_RELATION,
            {
                "src_name": rel.source,
                "tgt_name": rel.target,
                "ws": workspace_id,
                "rtype": rel.type,
                "src": SOURCE,
                "hop": rel.hop,
            },
        )
    for alias, canonical in graph.aliases:
        session.run(
            _CYPHER_ALIAS,
            {
                "alias": alias,
                "canon": canonical,
                "ws": workspace_id,
                "etype": graph.entities[alias],
                "src": SOURCE,
            },
        )


def unique_documents(graphs: Iterable[QuestionGraph]) -> list[dict[str, Any]]:
    """Distinct paragraphs across questions, with the qids that use / are supported by them."""
    merged: dict[str, dict[str, Any]] = {}
    for g in graphs:
        for doc in g.documents:
            entry = merged.setdefault(
                doc.doc_label,
                {"doc": doc, "qids": [], "supporting_qids": []},
            )
            if doc.qid not in entry["qids"]:
                entry["qids"].append(doc.qid)
            if doc.is_supporting and doc.qid not in entry["supporting_qids"]:
                entry["supporting_qids"].append(doc.qid)
    return list(merged.values())


def write_documents(store: VectorStore, graphs: Iterable[QuestionGraph]) -> int:
    """One Qdrant point set per distinct paragraph (add_document may split long text)."""
    entries = unique_documents(graphs)
    for entry in entries:
        doc: DocSpec = entry["doc"]
        store.add_document(
            doc.text,
            metadata={
                "doc_label": doc.doc_label,
                "title": doc.title,
                "type": SOURCE,
                "source": SOURCE,
                "qids": entry["qids"],
                "supporting_qids": entry["supporting_qids"],
            },
            doc_id=doc.doc_label,
        )
    return len(entries)


def llm_document_text(doc: DocSpec) -> str:
    """Text handed to the production extractor: the paragraph under its title, as a
    short ingested document would read."""
    return f"{doc.title}\n\n{doc.text}"


def write_llm_graph(
    graphs: Iterable[QuestionGraph],
    workspace_id: str,
    write_doc_graph,
    already_written: set[str] | None = None,
    progress=None,
) -> int:
    """Build the graph with the production LLM extractor instead of the oracle.

    ``write_doc_graph`` is metronix.storage.neo4j_graph.write_doc_graph (injected for
    tests). Documents in ``already_written`` are skipped so an interrupted run resumes.
    Returns the number of documents extracted in this call.
    """
    done = set(already_written or ())
    entries = [e for e in unique_documents(graphs) if e["doc"].doc_label not in done]
    for i, entry in enumerate(entries, 1):
        doc: DocSpec = entry["doc"]
        write_doc_graph(
            llm_document_text(doc),
            file_name=doc.title,
            workspace_id=workspace_id,
            doc_label=doc.doc_label,
        )
        if progress:
            progress(i, len(entries), doc.doc_label)
    return len(entries)


def summarize(graphs: Iterable[QuestionGraph]) -> dict[str, int]:
    graphs = list(graphs)
    return {
        "questions": len(graphs),
        "documents": len(unique_documents(graphs)),
        "document_occurrences": sum(len(g.documents) for g in graphs),
        "supporting_documents": len(
            {d.doc_label for g in graphs for d in g.documents if d.is_supporting}
        ),
        "entities": len({name for g in graphs for name in g.entities}),
        "mentions": sum(len(g.mentions) for g in graphs),
        "relations": sum(len(g.relations) for g in graphs),
        "aliases": sum(len(g.aliases) for g in graphs),
    }


def write_manifest(graphs: Iterable[QuestionGraph], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for g in graphs:
            handle.write(json.dumps(g.manifest(), ensure_ascii=False) + "\n")


def main() -> None:
    import argparse

    from benchmarks.musique.scripts.dataset import load_records

    parser = argparse.ArgumentParser(description="Load MuSiQue 2-hop slice into Metronix")
    parser.add_argument(
        "--input", type=Path, default=Path("benchmarks/musique/data/dev_2hop.jsonl")
    )
    parser.add_argument("--workspace", default="musique-dev")
    parser.add_argument(
        "--manifest", type=Path, default=Path("benchmarks/musique/data/manifest.jsonl")
    )
    parser.add_argument("--no-distractors", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="build + manifest only")
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument(
        "--reset", action="store_true", help="wipe the workspace graph and collection first"
    )
    parser.add_argument(
        "--graph",
        choices=["oracle", "llm"],
        default="oracle",
        help="oracle: edges from question_decomposition; llm: production write_doc_graph",
    )
    parser.add_argument(
        "--label-prefix",
        default=SOURCE,
        help="doc_label prefix; use a distinct one per workspace (Documents MERGE on doc_id)",
    )
    parser.add_argument("--limit", type=int, help="only the first N questions")
    args = parser.parse_args()

    records = load_records(args.input)[: args.limit]
    graphs = [
        build_question_graph(
            r, include_distractors=not args.no_distractors, label_prefix=args.label_prefix
        )
        for r in records
    ]
    write_manifest(graphs, args.manifest)
    print(json.dumps(summarize(graphs), indent=2))
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
        write_documents(store, graphs)
    if args.graph == "oracle":
        with get_graph_driver().session() as session:
            for g in graphs:
                write_graph(session, g, args.workspace)
    else:
        from metronix.storage.neo4j_graph import write_doc_graph

        with get_graph_driver().session() as session:
            written = {
                r["dl"]
                for r in session.run(
                    "MATCH (d:Document) WHERE d.workspace_id = $ws AND d.raw_text IS NOT NULL "
                    "RETURN d.doc_label AS dl",
                    {"ws": args.workspace},
                )
            }

        def progress(i: int, total: int, label: str) -> None:
            print(f"[llm-graph] {i}/{total} {label}", flush=True)

        write_llm_graph(graphs, args.workspace, write_doc_graph, written, progress)
    print(f"loaded {len(graphs)} questions into workspace {args.workspace!r}")


if __name__ == "__main__":
    main()
