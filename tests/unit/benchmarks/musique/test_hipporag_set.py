from __future__ import annotations

from benchmarks.musique.scripts.convert import paragraph_label
from benchmarks.musique.scripts.hipporag_set import build_openie_graph, phrase_key


def test_phrase_key_matches_hipporag_normalisation() -> None:
    assert phrase_key("German Aerospace Center (DLR)") == "german aerospace center dlr"
    assert phrase_key("  Rosetta-Stone ") == "rosetta stone"
    assert phrase_key("!!!") == ""


def test_build_openie_graph_canonicalises_surface_forms() -> None:
    docs = [
        {
            "title": "A",
            "text": "t1",
            "extracted_entities": ["Cologne", "German Aerospace Center"],
            "extracted_triples": [["German Aerospace Center", "headquartered in", "Cologne"]],
        },
        {
            "title": "B",
            "text": "t2",
            "extracted_entities": ["german aerospace center"],
            "extracted_triples": [
                ["Ulrich Walter", "worked for", "German Aerospace Center"],
                ["x"],
            ],
        },
    ]
    graph = build_openie_graph(docs, "p")
    a, b = paragraph_label("A", "t1", "p"), paragraph_label("B", "t2", "p")
    # "German Aerospace Center" (3 occurrences) beats "german aerospace center" (1).
    assert graph.mentions[a] == {"Cologne", "German Aerospace Center"}
    assert graph.mentions[b] == {"German Aerospace Center", "Ulrich Walter"}
    assert graph.triples == {
        ("German Aerospace Center", "headquartered in", "Cologne"),
        ("Ulrich Walter", "worked for", "German Aerospace Center"),
    }
    assert graph.summary()["entities"] == 3


def test_title_entity_drops_disambiguation() -> None:
    from benchmarks.musique.scripts.hipporag_set import title_entity

    assert title_entity("Theodred II (Bishop of Elmham)") == "Theodred II"
    assert title_entity("Lothair II") == "Lothair II"


def test_build_title_graph_links_titles_named_in_text() -> None:
    from benchmarks.musique.scripts.hipporag_set import build_title_graph

    corpus = {
        "a": {"title": "Lothair II", "text": "Lothair II's mother was Ermengarde of Tours."},
        "b": {"title": "Ermengarde of Tours", "text": "She died in 851."},
        "c": {"title": "Love (film)", "text": "A film about love and Tours."},
        "d": {"title": "1851", "text": "A year."},
    }
    graph = build_title_graph(corpus)
    assert graph.mentions["a"] == {"Lothair II", "Ermengarde of Tours"}
    assert graph.mentions["b"] == {"Ermengarde of Tours"}
    # Case-sensitive: "love" does not link to "Love"; "Tours" alone is not a title.
    assert graph.mentions["c"] == {"Love"}
    # Pure numbers are not linkable, but a passage still mentions its own title.
    assert graph.mentions["d"] == {"1851"}


def test_twowiki_manifest_orders_gold_by_supporting_facts() -> None:
    from benchmarks.musique.scripts.hipporag_set import twowiki_manifest

    corpus = {"la": {"title": "A", "text": "x"}, "lb": {"title": "B", "text": "y"}}
    record = {
        "_id": "q1",
        "question": "?",
        "answer": "z",
        "type": "compositional",
        "supporting_facts": [["B", 1], ["A", 0], ["B", 0], ["C", 0]],
    }
    (row,) = twowiki_manifest([record], corpus)
    assert [h["doc_label"] for h in row["hops"]] == ["lb", "la"]
    assert row["supporting_doc_labels"] == ["lb", "la"]
    assert row["missing_gold_titles"] == ["C"]
    assert row["hop_count"] == 2
