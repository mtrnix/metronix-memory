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
