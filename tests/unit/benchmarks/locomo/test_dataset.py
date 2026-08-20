from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.locomo.scripts.dataset import (
    dataset_summary,
    iter_questions,
    load_dataset,
    sessions_from_conversation,
)


def sample_dataset() -> list[dict]:
    return [
        {
            "sample_id": "conv-1",
            "conversation": {
                "speaker_a": "A",
                "speaker_b": "B",
                "session_1_date_time": "1 Jan 2024",
                "session_1": [{"speaker": "A", "text": "Hello", "dia_id": "D1:1"}],
                "session_2_date_time": "2 Jan 2024",
            },
            "qa": [
                {"question": "Q1?", "answer": "A1", "category": 1, "evidence": ["D1:1"]},
                {"question": "Q2?", "answer": "A2", "category": 5, "evidence": []},
            ],
        }
    ]


def test_load_dataset_validates_shape(tmp_path: Path) -> None:
    path = tmp_path / "locomo10.json"
    path.write_text(json.dumps(sample_dataset()), encoding="utf-8")

    assert load_dataset(path)[0]["sample_id"] == "conv-1"

    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_dataset(path)


def test_sessions_ignore_date_only_placeholders() -> None:
    sessions, dates = sessions_from_conversation(sample_dataset()[0]["conversation"])

    assert sessions == [[{"speaker": "A", "text": "Hello", "dia_id": "D1:1"}]]
    assert dates == ["1 Jan 2024"]


def test_iter_questions_filters_categories_and_assigns_stable_ids() -> None:
    rows = list(iter_questions(sample_dataset(), categories={1}))

    assert [row["question_id"] for row in rows] == ["conv-1-q0001"]
    assert rows[0]["category"] == 1


def test_dataset_summary_counts_categories() -> None:
    assert dataset_summary(sample_dataset()) == {
        "conversation_count": 1,
        "question_count": 2,
        "category_counts": {"1": 1, "5": 1},
    }
