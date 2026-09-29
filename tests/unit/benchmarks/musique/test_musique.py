from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from benchmarks.musique.scripts.convert import (
    build_question_graph,
    paragraph_label,
    relation_type,
    step_subject,
    summarize,
    unique_documents,
    write_documents,
    write_graph,
    write_manifest,
)
from benchmarks.musique.scripts.dataset import (
    _to_py,
    find_dev_file,
    load_records,
    select_two_hop,
    validate_record,
)
from benchmarks.musique.scripts.probe import aggregate, dense_ranks, score_question, trace_bfs


def _para(idx: int, title: str, text: str, supporting: bool = False) -> dict:
    return {"idx": idx, "title": title, "paragraph_text": text, "is_supporting": supporting}


def _label(record: dict, idx: int) -> str:
    p = next(p for p in record["paragraphs"] if p["idx"] == idx)
    return paragraph_label(p["title"], p["paragraph_text"])


def arrow_record() -> dict:
    """2-hop question in the ``subject >> relation`` / ``#1 >> relation`` style."""
    return {
        "id": "2hop__100_200",
        "question": "Who is the spouse of the Green performer?",
        "answer": "Miquette Giraudy",
        "answer_aliases": [],
        "answerable": True,
        "paragraphs": [
            _para(0, "Green (album)", "Green is an album by Steve Hillage.", True),
            _para(1, "Green Day", "Green Day is a rock band."),
            _para(2, "Steve Hillage", "Steve Hillage married Miquette Giraudy.", True),
            _para(3, "Hillage Island", "An island unrelated to music."),
        ],
        "question_decomposition": [
            {
                "id": 100,
                "question": "Green >> performer",
                "answer": "Steve Hillage",
                "paragraph_support_idx": 0,
            },
            {
                "id": 200,
                "question": "#1 >> spouse",
                "answer": "Miquette Giraudy",
                "paragraph_support_idx": 2,
            },
        ],
    }


def prose_record() -> dict:
    """2-hop question with free-text sub-questions and no ``>>`` subject."""
    return {
        "id": "2hop__300_400",
        "question": "Who founded the label that signed Nova Quartet?",
        "answer": "Ada Byrne",
        "answerable": True,
        "paragraphs": [
            _para(0, "Nova Quartet", "Nova Quartet signed with Tidewave Records.", True),
            _para(1, "Tidewave Records", "Tidewave Records was founded by Ada Byrne.", True),
        ],
        "question_decomposition": [
            {
                "id": 300,
                "question": "Which label signed Nova Quartet?",
                "answer": "Tidewave Records",
                "paragraph_support_idx": 0,
            },
            {
                "id": 400,
                "question": "Who founded #1?",
                "answer": "Ada Byrne",
                "paragraph_support_idx": 1,
            },
        ],
    }


def three_hop_record() -> dict:
    rec = arrow_record()
    rec["id"] = "3hop1__1_2_3"
    rec["question_decomposition"] = rec["question_decomposition"] + [
        {"id": 3, "question": "#2 >> birthplace", "answer": "Paris", "paragraph_support_idx": 3}
    ]
    return rec


# --- dataset -----------------------------------------------------------------


def test_select_two_hop_filters_hops_and_unanswerable() -> None:
    unanswerable = {**prose_record(), "id": "2hop__9_9", "answerable": False}
    records = [three_hop_record(), unanswerable, arrow_record(), prose_record()]
    assert [r["id"] for r in select_two_hop(records, 10)] == ["2hop__100_200", "2hop__300_400"]
    assert [r["id"] for r in select_two_hop(records, 1)] == ["2hop__100_200"]


def test_load_records_jsonl_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "dev.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [arrow_record(), prose_record()]) + "\n")
    assert [r["id"] for r in load_records(path)] == ["2hop__100_200", "2hop__300_400"]


def test_to_py_unwraps_parquet_arrays() -> None:
    row = {"paragraphs": np.array([{"idx": np.int64(1), "tags": np.array(["a"])}])}
    assert _to_py(row) == {"paragraphs": [{"idx": 1, "tags": ["a"]}]}


def test_validate_record_rejects_missing_decomposition() -> None:
    bad = {**arrow_record(), "question_decomposition": []}
    with pytest.raises(ValueError, match="question_decomposition"):
        validate_record(bad)


def test_find_dev_file_prefers_ans_jsonl() -> None:
    files = [
        "musique_full_v1.0_dev.jsonl",
        "data/validation-00000.parquet",
        "musique_ans_v1.0_train.jsonl",
        "musique_ans_v1.0_dev.jsonl",
    ]
    assert find_dev_file(files) == "musique_ans_v1.0_dev.jsonl"
    assert find_dev_file(["data/validation-00000.parquet"]) == "data/validation-00000.parquet"
    with pytest.raises(ValueError):
        find_dev_file(["README.md"])


# --- graph construction ------------------------------------------------------


def test_relation_type_and_subject_parsing() -> None:
    assert relation_type("Green >> performer") == "performer"
    assert relation_type("#1 >> place of birth") == "place_of_birth"
    assert relation_type("Who founded #1?") == "who_founded"
    assert step_subject("#1 >> spouse", ["Steve Hillage"], "t") == "Steve Hillage"
    assert step_subject("Green >> performer", [], "Green (album)") == "Green"
    assert step_subject("Which label signed X?", [], "Nova Quartet") == "Nova Quartet"


def test_arrow_record_graph() -> None:
    g = build_question_graph(arrow_record())
    p0, p2 = _label(arrow_record(), 0), _label(arrow_record(), 2)

    assert g.seed_entity == "Green"
    assert [(h.hop, h.doc_label, h.subject, h.relation, h.answer) for h in g.hops] == [
        (0, p0, "Green", "performer", "Steve Hillage"),
        (1, p2, "Steve Hillage", "spouse", "Miquette Giraudy"),
    ]
    assert [(r.source, r.target, r.type) for r in g.relations] == [
        ("Green", "Steve Hillage", "performer"),
        ("Steve Hillage", "Miquette Giraudy", "spouse"),
    ]
    assert len(g.documents) == 4
    assert {(d.doc_label, d.is_supporting) for d in g.documents if d.is_supporting} == {
        (p0, True),
        (p2, True),
    }
    # Title "Steve Hillage" is both a title and the step-0 answer: title type wins.
    assert g.entities["Steve Hillage"] == "musique_title"
    assert (p0, "Steve Hillage") in g.mentions and (p2, "Steve Hillage") in g.mentions
    # Distractors mention only their own title.
    assert [n for dl, n in g.mentions if dl == _label(arrow_record(), 1)] == ["Green Day"]


def test_without_distractors_only_supporting_docs() -> None:
    g = build_question_graph(arrow_record(), include_distractors=False)
    assert all(d.is_supporting for d in g.documents)
    assert len(g.documents) == 2


def test_prose_record_falls_back_to_title_seed() -> None:
    g = build_question_graph(prose_record())
    assert g.seed_entity == "Nova Quartet"
    assert [(r.source, r.target) for r in g.relations] == [
        ("Nova Quartet", "Tidewave Records"),
        ("Tidewave Records", "Ada Byrne"),
    ]


def test_missing_support_paragraph_raises() -> None:
    rec = arrow_record()
    rec["question_decomposition"][1]["paragraph_support_idx"] = 99
    with pytest.raises(ValueError, match="missing paragraph 99"):
        build_question_graph(rec)


def test_summarize_and_manifest(tmp_path: Path) -> None:
    graphs = [build_question_graph(arrow_record()), build_question_graph(prose_record())]
    stats = summarize(graphs)
    assert stats["questions"] == 2
    assert stats["documents"] == 6
    assert stats["supporting_documents"] == 4
    assert stats["relations"] == 4

    path = tmp_path / "manifest.jsonl"
    write_manifest(graphs, path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["seed_entity"] == "Green"
    assert rows[0]["distractor_count"] == 2
    assert rows[0]["distractor_doc_labels"] == [
        _label(arrow_record(), 1),
        _label(arrow_record(), 3),
    ]
    assert [h["hop"] for h in rows[0]["hops"]] == [0, 1]


# --- writers -----------------------------------------------------------------


def test_write_graph_emits_documents_mentions_relations() -> None:
    g = build_question_graph(arrow_record())
    session = MagicMock()
    write_graph(session, g, "musique-dev")

    calls = [(c[0][0], c[0][1]) for c in session.run.call_args_list]
    docs = [p for q, p in calls if q.startswith("MERGE (d:Document")]
    mentions = [p for q, p in calls if "MERGE (d)-[:MENTIONS]->(e)" in q]
    rels = [p for q, p in calls if ":RELATION {type: $rtype" in q]

    assert len(docs) == 4 and len(mentions) == len(g.mentions) and len(rels) == 2
    assert all(p["ws"] == "musique-dev" for _, p in calls)
    assert {p["dl"] for p in docs} == {d.doc_label for d in g.documents}
    assert rels[1] == {
        "src_name": "Steve Hillage",
        "tgt_name": "Miquette Giraudy",
        "ws": "musique-dev",
        "rtype": "spouse",
        "src": "musique",
        "hop": 1,
    }
    # Documents are written before the MENTIONS that MATCH them.
    first_mention = next(i for i, (q, _) in enumerate(calls) if "MENTIONS" in q)
    assert all(q.startswith("MERGE (d:Document") for q, _ in calls[:first_mention])


def test_write_documents_payload() -> None:
    g = build_question_graph(arrow_record())
    store = MagicMock()
    assert write_documents(store, [g]) == 4
    (text,) = store.add_document.call_args_list[0][0]
    kwargs = store.add_document.call_args_list[0][1]
    assert text == "Green is an album by Steve Hillage."
    assert kwargs["doc_id"] == _label(arrow_record(), 0)
    assert kwargs["metadata"]["doc_label"] == kwargs["doc_id"]
    assert kwargs["metadata"]["qids"] == [g.qid]
    assert kwargs["metadata"]["supporting_qids"] == [g.qid]
    assert kwargs["metadata"]["title"] == "Green (album)"


# --- paragraph deduplication across and within questions ----------------------


def shared_record() -> dict:
    """Another question reusing arrow_record's paragraphs: p2 as a distractor here."""
    base = arrow_record()
    return {
        "id": "2hop__500_600",
        "question": "Where was the Green performer born?",
        "answer": "Paddington",
        "answerable": True,
        "paragraphs": [
            {**base["paragraphs"][0], "idx": 0},
            {**base["paragraphs"][2], "idx": 1, "is_supporting": False},
            _para(2, "Paddington", "Steve Hillage was born in Paddington.", True),
        ],
        "question_decomposition": [
            {
                "id": 500,
                "question": "Green >> performer",
                "answer": "Steve Hillage",
                "paragraph_support_idx": 0,
            },
            {
                "id": 600,
                "question": "#1 >> place of birth",
                "answer": "Paddington",
                "paragraph_support_idx": 2,
            },
        ],
    }


def test_paragraph_label_is_content_based() -> None:
    assert paragraph_label("Green (album)", "x") == paragraph_label(" Green  (album) ", "x ")
    assert paragraph_label("Green (album)", "x") != paragraph_label("Green (album)", "y")
    a, b = build_question_graph(arrow_record()), build_question_graph(shared_record())
    assert a.hops[0].doc_label == b.hops[0].doc_label


def test_shared_paragraphs_written_once_with_all_qids() -> None:
    graphs = [build_question_graph(arrow_record()), build_question_graph(shared_record())]
    stats = summarize(graphs)
    assert stats["document_occurrences"] == 7
    assert stats["documents"] == 5
    assert stats["supporting_documents"] == 3  # p0 shared, p2 (arrow), Paddington

    store = MagicMock()
    assert write_documents(store, graphs) == 5
    meta = {c[1]["doc_id"]: c[1]["metadata"] for c in store.add_document.call_args_list}
    shared_p2 = _label(arrow_record(), 2)
    assert meta[shared_p2]["qids"] == ["2hop__100_200", "2hop__500_600"]
    assert meta[shared_p2]["supporting_qids"] == ["2hop__100_200"]
    assert [e["doc"].doc_label for e in unique_documents(graphs)].count(shared_p2) == 1


def test_duplicate_within_question_keeps_supporting_copy() -> None:
    rec = arrow_record()
    rec["paragraphs"].append({**rec["paragraphs"][2], "idx": 4, "is_supporting": False})
    g = build_question_graph(rec)
    assert len(g.documents) == 4
    p2 = _label(rec, 2)
    assert [d.is_supporting for d in g.documents if d.doc_label == p2] == [True]
    assert p2 not in g.manifest()["distractor_doc_labels"]


def test_write_graph_doc_params_accumulate_qids() -> None:
    g = build_question_graph(shared_record())
    session = MagicMock()
    write_graph(session, g, "musique-dev")
    doc_calls = [c[0] for c in session.run.call_args_list if c[0][0].startswith("MERGE (d:Doc")]
    query = doc_calls[0][0]
    assert "d.qids" in query and "d.supporting_qids" in query
    params = {c[1]["dl"]: c[1] for c in doc_calls}
    assert params[_label(arrow_record(), 2)]["sup"] is False
    assert params[_label(arrow_record(), 2)]["qid"] == "2hop__500_600"


# --- probe over an in-memory graph built from the converter output ------------


class FakeGraph:
    """Answers the two graph_ops calls BFS uses, from QuestionGraph specs."""

    def __init__(self, graphs, blank_names: bool = False) -> None:
        self.doc_labels: dict[str, set[str]] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.blank_names = blank_names
        for g in graphs:
            for dl, name in g.mentions:
                self.doc_labels.setdefault(name, set()).add(dl)
            self.edges += [(r.source, r.target, r.type) for r in g.relations]

    def get_relationships(self, names, workspace_id=None, max_depth=1):
        names = set(names)
        rows = [
            {"source": s, "target": t, "type": ty}
            for s, t, ty in self.edges
            if s in names or t in names
        ]
        if self.blank_names:  # pre-#508 behaviour: endpoint names read as ""
            rows = [{**r, "source": "", "target": ""} for r in rows]
        return rows

    def get_doc_labels(self, names, workspace_id=None):
        return [
            {"doc_label": dl, "title": n}
            for n in names
            for dl in sorted(self.doc_labels.get(n, ()))
        ]


def _trace(fake: FakeGraph, seeds, max_depth: int = 2):
    return trace_bfs(seeds, "musique-dev", max_depth, fake.get_relationships, fake.get_doc_labels)


def test_shared_gold_paragraph_counts_for_both_questions() -> None:
    graphs = [build_question_graph(arrow_record()), build_question_graph(shared_record())]
    fake = FakeGraph(graphs)
    for g in graphs:
        row = score_question(g.manifest(), _trace(fake, [g.seed_entity]))
        assert row["all_gold_found"] and row["last_hop_via_bfs"]
    # arrow's gold p2 is a distractor for shared_record and is counted as such there.
    row = score_question(graphs[1].manifest(), _trace(fake, [graphs[1].seed_entity]))
    assert row["same_question_distractors_found"] == 1


def test_bfs_reaches_last_hop_paragraph_at_hop_one() -> None:
    graphs = [build_question_graph(arrow_record()), build_question_graph(prose_record())]
    fake = FakeGraph(graphs)
    for g in graphs:
        trace = _trace(fake, [g.seed_entity])
        row = score_question(g.manifest(), trace)
        assert row["gold_found_at_hop"] == {g.hops[0].doc_label: 0, g.hops[1].doc_label: 1}
        assert row["last_hop_via_bfs"] and row["all_gold_found"]


def test_bfs_with_blank_names_never_expands() -> None:
    g = build_question_graph(arrow_record())
    trace = _trace(FakeGraph([g], blank_names=True), [g.seed_entity])
    row = score_question(g.manifest(), trace)
    assert row["gold_found_at_hop"][g.hops[1].doc_label] is None
    assert not row["last_hop_via_bfs"]


def test_distractor_sharing_title_is_counted() -> None:
    rec = arrow_record()
    rec["paragraphs"][1]["title"] = "Green"  # distractor titled like the seed
    g = build_question_graph(rec)
    row = score_question(g.manifest(), _trace(FakeGraph([g]), [g.seed_entity]))
    assert row["same_question_distractors_found"] == 1


def test_depth_zero_and_no_seed() -> None:
    g = build_question_graph(arrow_record())
    fake = FakeGraph([g])
    assert not score_question(g.manifest(), _trace(fake, [g.seed_entity], 0))["last_hop_via_bfs"]
    empty = score_question(g.manifest(), _trace(fake, []))
    assert empty["seeds"] == [] and not empty["all_gold_found"]
    assert aggregate([empty])["no_seed"] == 1


def test_aliases_extend_seeds() -> None:
    g = build_question_graph(arrow_record())
    fake = FakeGraph([g])
    trace = trace_bfs(
        ["Green album"],
        "musique-dev",
        2,
        fake.get_relationships,
        fake.get_doc_labels,
        resolve_aliases=lambda names, ws: {"Green album": ["Green"]},
    )
    assert trace.hop_of(g.hops[1].doc_label) == 1


# --- answer_aliases -> ALIAS edges --------------------------------------------


def aliased_record() -> dict:
    rec = arrow_record()
    rec["answer_aliases"] = ["Miquette  Giraudy", "M. Giraudy", "miquette giraudy", ""]
    return rec


def test_answer_aliases_become_alias_edges_to_final_answer() -> None:
    g = build_question_graph(aliased_record())
    # Whitespace-normalised duplicate, case-only duplicate and blank are dropped.
    assert g.aliases == [("M. Giraudy", "Miquette Giraudy")]
    assert g.entities["M. Giraudy"] == "musique_alias"
    assert g.manifest()["answer_aliases"] == ["M. Giraudy"]
    assert summarize([g])["aliases"] == 1


def test_alias_matching_existing_entity_is_skipped() -> None:
    rec = arrow_record()
    rec["answer_aliases"] = ["Steve Hillage"]  # already an entity in this question
    assert build_question_graph(rec).aliases == []


def test_write_graph_emits_alias_edges() -> None:
    g = build_question_graph(aliased_record())
    session = MagicMock()
    write_graph(session, g, "musique-dev")
    alias_calls = [c[0][1] for c in session.run.call_args_list if ":ALIAS]" in c[0][0]]
    assert alias_calls == [
        {
            "alias": "M. Giraudy",
            "canon": "Miquette Giraudy",
            "ws": "musique-dev",
            "etype": "musique_alias",
            "src": "musique",
        }
    ]
    query = next(c[0][0] for c in session.run.call_args_list if ":ALIAS]" in c[0][0])
    assert "MERGE (a)-[:ALIAS]->(c)" in query


def test_missing_answer_aliases_field() -> None:
    rec = arrow_record()
    del rec["answer_aliases"]
    assert build_question_graph(rec).aliases == []


# --- dense-channel metrics -----------------------------------------------------


def test_dense_ranks_dedupes_chunks_of_same_doc() -> None:
    labels = ["a", "a", "x", "b", "x"]
    assert dense_ranks(["a", "b", "c"], labels) == {"a": 1, "b": 3, "c": None}


def test_aggregate_dense_and_union() -> None:
    base = {"seeds": ["s"], "all_gold_found": True, "last_hop_via_bfs": True}
    rows = [
        {**base, "dense_gold_rank": {"g0": 1, "g1": 12}, "recall_graph_labels": []},
        {**base, "dense_gold_rank": {"g0": 3, "g1": None}, "recall_graph_labels": ["g1"]},
        {**base, "dense_gold_rank": {"g0": None, "g1": 4}, "recall_graph_labels": []},
    ]
    s = aggregate(rows)
    assert s["dense@5"] == {"hop0": 2, "last_hop": 1, "both": 0}
    assert s["dense@30"] == {"hop0": 2, "last_hop": 2, "both": 1}
    assert s["dense@30_or_graph"] == {"last_hop": 3, "both": 2, "last_hop_only_via_graph": 1}
    assert s["graph"] == {"hop0": 0, "last_hop": 1, "both": 0, "empty": 2}
    assert "ppr" not in s


def test_aggregate_ppr_channel() -> None:
    base = {"seeds": ["s"], "all_gold_found": True, "last_hop_via_bfs": True}
    rows = [
        {**base, "dense_gold_rank": {"g0": 1, "g1": None}, "ppr_labels": ["g0", "g1"]},
        {**base, "dense_gold_rank": {"g0": 2, "g1": None}, "ppr_labels": ["g0"]},
    ]
    s = aggregate(rows)
    assert s["ppr"] == {"hop0": 2, "last_hop": 1, "both": 1, "empty": 0}
    assert s["dense@30_or_ppr"] == {"last_hop": 1, "both": 1, "last_hop_only_via_graph": 1}


def test_aggregate_without_dense_has_no_dense_keys() -> None:
    row = {"seeds": [], "all_gold_found": False, "last_hop_via_bfs": False}
    assert not any(k.startswith("dense") for k in aggregate([row]))
