from __future__ import annotations

import pytest

from benchmarks.locomo.scripts import evaluate
from benchmarks.locomo.scripts.evaluate import evaluate_rows, score_answer


@pytest.fixture(autouse=True)
def deterministic_stemmer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluate, "_stem", lambda word: word)


@pytest.mark.parametrize(
    ("category", "hypothesis", "answer", "expected"),
    [
        (1, "Paris, Rome", "Paris, Rome", 1.0),
        (2, "She visited Paris", "Paris", 0.5),
        (3, "May 2024", "May 2024; around spring", 1.0),
        (5, "No information available.", "", 1.0),
        (5, "Paris", "", 0.0),
    ],
)
def test_score_answer_matches_upstream_category_rules(
    category: int, hypothesis: str, answer: str, expected: float
) -> None:
    assert score_answer(category, hypothesis, answer) == pytest.approx(expected)


def test_evaluate_rows_reports_overall_category_and_errors() -> None:
    report = evaluate_rows(
        [
            {"category": 2, "hypothesis": "Paris", "answer": "Paris"},
            {"category": 2, "hypothesis": "Error: timeout", "answer": "Rome"},
            {"category": 5, "hypothesis": "Not mentioned", "answer": ""},
        ]
    )

    assert report["question_count"] == 3
    assert report["error_count"] == 1
    assert report["overall_score"] == pytest.approx(2 / 3)
    assert report["category_scores"] == {"2": 0.5, "5": 1.0}
