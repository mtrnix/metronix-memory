from __future__ import annotations

import sys
from pathlib import Path

import pytest

from benchmarks._shared import oracle

BENCH = Path(__file__).resolve().parents[4] / "benchmarks"
sys.path.insert(0, str(BENCH / "longmemeval" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


# ---------------------------------------------------------------------------
# retrieved_session_tags
# ---------------------------------------------------------------------------


def test_retrieved_session_tags_one_per_hit_in_order() -> None:
    hits = [
        {"record": {"tags": ["date_x", "session_3"]}},
        {"record": {"tags": ["session_0", "session_1"]}},  # first wins
        {"record": {"tags": ["no-session-tag"]}},  # dropped
        {"record": {}},
    ]
    assert oracle.retrieved_session_tags(hits) == ["session_3", "session_0"]


# ---------------------------------------------------------------------------
# LongMemEval
# ---------------------------------------------------------------------------


def test_longmemeval_oracle_maps_answer_ids_by_position() -> None:
    entry = {
        "question_id": "q1",
        "haystack_session_ids": ["a", "b", "c", "d"],
        "answer_session_ids": ["c", "a"],
    }
    assert oracle.longmemeval_oracle_tags(entry) == {"session_2", "session_0"}


def test_longmemeval_oracle_skips_unknown_answer_id() -> None:
    entry = {"haystack_session_ids": ["a"], "answer_session_ids": ["a", "zzz"]}
    assert oracle.longmemeval_oracle_tags(entry) == {"session_0"}


@pytest.mark.parametrize(
    ("qid", "expected"),
    [("gpt4_2655b836", False), ("gpt4_9c8f_abs", True)],
)
def test_longmemeval_abstention_detection(qid: str, expected: bool) -> None:
    assert oracle.longmemeval_is_abstention({"question_id": qid}) is expected


# ---------------------------------------------------------------------------
# LoCoMo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ("['D1:3']", ["D1:3"]),
        ("['D2:8', 'D3:1']", ["D2:8", "D3:1"]),
        ("D1:5", ["D1:5"]),
        ("[]", []),
        ("", []),
        ("not a list", ["not a list"]),
        (["D1:1"], ["D1:1"]),
    ],
)
def test_parse_evidence_handles_repr_strings(evidence: object, expected: list[str]) -> None:
    assert oracle._parse_evidence(evidence) == expected


def test_locomo_oracle_maps_dia_number_to_ingest_position() -> None:
    # sessions ingested in sorted order: [1, 3, 10] -> session_0, session_1, session_2
    entry = {"session_numbers": [1, 3, 10], "evidence": "['D3:4', 'D10:1']", "category": 2}
    assert oracle.locomo_oracle_tags(entry) == {"session_1", "session_2"}


def test_locomo_oracle_empty_evidence_is_empty() -> None:
    assert oracle.locomo_oracle_tags({"session_numbers": [1, 2], "evidence": "[]"}) == set()


def test_locomo_abstention_is_category_5() -> None:
    assert oracle.locomo_is_abstention({"category": 5}) is True
    assert oracle.locomo_is_abstention({"category": "5"}) is True
    assert oracle.locomo_is_abstention({"category": 2}) is False


# ---------------------------------------------------------------------------
# Real-data checks (skipped in a clean checkout)
# ---------------------------------------------------------------------------


def test_real_longmemeval_every_non_abstention_question_has_an_oracle() -> None:
    import dataset as lme_dataset  # noqa: PLC0415

    if not lme_dataset.dataset_path("oracle").exists():
        pytest.skip("longmemeval oracle dataset not downloaded")
    data = lme_dataset.load_dataset("oracle")
    for entry in data:
        tags = oracle.longmemeval_oracle_tags(entry)
        if not oracle.longmemeval_is_abstention(entry):
            assert tags, f"{entry['question_id']} has no oracle session"
        assert all(t.startswith("session_") for t in tags)


def test_real_locomo_oracle_coverage() -> None:
    from benchmarks.locomo.scripts import dataset as locomo_dataset  # noqa: PLC0415

    if not locomo_dataset.DATASET_PATH.exists():
        pytest.skip("locomo dataset not downloaded")
    data = locomo_dataset.load_dataset(locomo_dataset.DATASET_PATH)
    missing = 0
    for entry in locomo_dataset.iter_questions(data, categories={1, 2, 3, 4}):
        tags = oracle.locomo_oracle_tags(entry)
        assert all(t.startswith("session_") for t in tags)
        if not tags:
            missing += 1
    # A handful of category-3 questions have empty evidence upstream; the rest resolve.
    assert missing <= 10
