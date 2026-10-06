from __future__ import annotations

import pytest

from benchmarks.freshness.conflict_pairs import (
    conflict_pairs,
    gated_pairs,
    label_pair,
    parse_facts,
    parse_triple,
    prf,
)


def test_parse_facts_keeps_serial_order() -> None:
    context = "Here is a list of facts:\n0. A is married to B.\n1. C is a citizen of D.\n\n2. x"
    assert parse_facts(context) == ["A is married to B.", "C is a citizen of D.", "x"]


def test_specific_templates_win_over_the_generic_one() -> None:
    assert parse_triple("The capital of Italy is Rome.") == (
        "The capital of {} is",
        "Italy",
        "Rome",
    )
    assert parse_triple("The Beatles is John.") == ("The {} is", "Beatles", "John")
    assert parse_triple(
        "The univeristy where Galileo Galilei was educated is University of Pisa."
    ) == (
        "The univeristy where {} was educated is",
        "Galileo Galilei",
        "University of Pisa",
    )
    assert parse_triple("Something else entirely") is None


def test_labels_and_conflicts() -> None:
    facts = [
        "Emilio Estefan is married to Gloria Estefan.",
        "Mat Latos is associated with the sport of baseball.",
        "Emilio Estefan is married to William Williams.",
        "Emilio Estefan is married to Gloria Estefan.",
        "Gloria Estefan is married to Emilio Estefan.",
    ]
    triples = [parse_triple(f) for f in facts]
    assert label_pair(triples[0], triples[2]) == "conflict"
    assert label_pair(triples[0], triples[3]) == "same"
    assert label_pair(triples[0], triples[4]) == "other"
    assert label_pair(triples[0], None) == "other"
    assert conflict_pairs(triples) == {(0, 2), (2, 3)}


def test_gated_pairs_respects_gate_and_top_k() -> None:
    vectors = [[1.0, 0.0], [0.99, 0.14], [0.0, 1.0], [0.98, 0.2]]
    pairs = gated_pairs(vectors, gate=0.9, top_k=1)
    assert set(pairs) == {(0, 1), (1, 3)}
    assert all(score >= 0.9 for score in pairs.values())
    assert gated_pairs(vectors, gate=0.9, top_k=3).keys() == {(0, 1), (0, 3), (1, 3)}


def test_prf() -> None:
    assert prf({1, 2, 3}, {2, 3, 4, 5}) == {
        "predicted": 3,
        "true_positive": 2,
        "precision": pytest.approx(0.667),
        "recall": 0.5,
        "f1": pytest.approx(0.571),
    }
    assert prf(set(), {1})["recall"] == 0.0
