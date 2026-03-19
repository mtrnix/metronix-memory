"""Tests for Benchmarker CRUD operations.

Validates:
- Property 5: average metrics computation
- Property 6: round-trip TestResult storage
- Property 7: workspace_id isolation
- Property 8: clone invariant

Uses SQLite in-memory via fixtures from conftest_benchmarker.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure conftest_benchmarker fixtures are available
from tests.unit.conftest_benchmarker import (
    db_session,
    patch_get_session,
    sqlite_engine,
)

from metatron.benchmarker.db import crud
from metatron.benchmarker.db.models import (
    BenchmarkQuestionRow,
    BenchmarkSetRow,
    TestResultRow,
    TestRunRow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_question_dict(text: str = "What is X?", qtype: str = "data_local") -> dict:
    return {
        "text": text,
        "question_type": qtype,
        "attributes": {"input_question": text, "reference_coverage": 0.5,
                        "relevant_reference_count": 1, "reference_count": 2,
                        "min_reference_similarity": 0.1, "max_reference_similarity": 0.9,
                        "mean_reference_similarity": 0.5, "intra_inter_similarity_ratio": 1.0,
                        "claim_count": 0},
        "references": ["ref1"],
    }


def _make_result_dict(
    answer: str = "Answer",
    correctness: float | None = 0.8,
    answer_relevancy: float | None = 0.7,
    faithfulness: float | None = 0.9,
    context_precision: float | None = 0.6,
    context_recall: float | None = 0.5,
    confidence: float | None = 1.0,
) -> dict:
    return {
        "actual_answer": answer,
        "question": {"text": "Q?"},
        "correctness": correctness,
        "answer_relevancy": answer_relevancy,
        "faithfulness": faithfulness,
        "context_precision": context_precision,
        "context_recall": context_recall,
        "confidence": confidence,
        "claim_scores": [{"claim": "c1", "score": 80}],
        "context": {"fragments": ["frag1"]},
    }


# ---------------------------------------------------------------------------
# BenchmarkSet CRUD
# ---------------------------------------------------------------------------


class TestCreateBenchmarkSet:
    def test_create_returns_row(self, db_session):
        bs = crud.create_benchmark_set(
            db_session, workspace_id="ws1", connection_id="conn-1", name="Test",
        )
        assert bs.id is not None
        assert bs.workspace_id == "ws1"
        assert bs.name == "Test"
        assert bs.connection_id == "conn-1"

    def test_create_with_all_fields(self, db_session):
        bs = crud.create_benchmark_set(
            db_session, workspace_id="ws1", connection_id="conn-1", name="Full",
            description="desc", tokens_used=100, question_count=5,
        )
        assert bs.description == "desc"
        assert bs.tokens_used == 100
        assert bs.question_count == 5


class TestReadBenchmarkSet:
    def test_get_by_id_and_workspace(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Test")
        db_session.flush()

        found = crud.get_benchmark_set(db_session, bs.id, "ws1")
        assert found is not None
        assert found.id == bs.id

    def test_get_returns_none_for_wrong_workspace(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Test")
        db_session.flush()

        found = crud.get_benchmark_set(db_session, bs.id, "ws_other")
        assert found is None

    def test_list_returns_all_for_workspace(self, db_session):
        crud.create_benchmark_set(db_session, "ws1", "conn-1", "A")
        crud.create_benchmark_set(db_session, "ws1", "conn-2", "B")
        crud.create_benchmark_set(db_session, "ws2", "conn-3", "C")
        db_session.flush()

        results = crud.get_benchmark_sets(db_session, "ws1")
        assert len(results) == 2


class TestUpdateBenchmarkSet:
    def test_update_name(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Old")
        db_session.flush()

        updated = crud.update_benchmark_set(db_session, bs.id, "ws1", name="New")
        assert updated is not None
        assert updated.name == "New"

    def test_update_nonexistent_returns_none(self, db_session):
        result = crud.update_benchmark_set(db_session, "fake-id", "ws1", name="X")
        assert result is None


class TestDeleteBenchmarkSet:
    def test_delete_existing(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Del")
        db_session.flush()

        deleted = crud.delete_benchmark_set(db_session, bs.id, "ws1")
        assert deleted is True

        found = crud.get_benchmark_set(db_session, bs.id, "ws1")
        assert found is None

    def test_delete_nonexistent_returns_false(self, db_session):
        assert crud.delete_benchmark_set(db_session, "fake", "ws1") is False

    def test_delete_wrong_workspace_returns_false(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "X")
        db_session.flush()

        assert crud.delete_benchmark_set(db_session, bs.id, "ws_other") is False


# ---------------------------------------------------------------------------
# Property 8: Clone invariant
# ---------------------------------------------------------------------------


class TestCloneBenchmarkSet:
    def test_clone_creates_new_id(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Original")
        crud.create_benchmark_questions(db_session, bs.id, [_make_question_dict()])
        db_session.flush()

        clone = crud.clone_benchmark_set(db_session, bs.id, "ws1")
        assert clone is not None
        assert clone.id != bs.id

    def test_clone_preserves_question_count(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Original",
                                        question_count=2)
        crud.create_benchmark_questions(db_session, bs.id, [
            _make_question_dict("Q1"), _make_question_dict("Q2"),
        ])
        db_session.flush()

        clone = crud.clone_benchmark_set(db_session, bs.id, "ws1")
        clone_qs = crud.get_benchmark_questions(db_session, clone.id)
        original_qs = crud.get_benchmark_questions(db_session, bs.id)

        assert len(clone_qs) == len(original_qs)

    def test_clone_question_texts_match(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Original")
        crud.create_benchmark_questions(db_session, bs.id, [
            _make_question_dict("Alpha?"), _make_question_dict("Beta?"),
        ])
        db_session.flush()

        clone = crud.clone_benchmark_set(db_session, bs.id, "ws1")
        clone_qs = crud.get_benchmark_questions(db_session, clone.id)
        original_qs = crud.get_benchmark_questions(db_session, bs.id)

        orig_texts = sorted(q.text for q in original_qs)
        clone_texts = sorted(q.text for q in clone_qs)
        assert orig_texts == clone_texts

    def test_clone_question_ids_differ(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "Original")
        crud.create_benchmark_questions(db_session, bs.id, [_make_question_dict()])
        db_session.flush()

        clone = crud.clone_benchmark_set(db_session, bs.id, "ws1")
        clone_qs = crud.get_benchmark_questions(db_session, clone.id)
        original_qs = crud.get_benchmark_questions(db_session, bs.id)

        orig_ids = {q.id for q in original_qs}
        clone_ids = {q.id for q in clone_qs}
        assert orig_ids.isdisjoint(clone_ids)

    def test_clone_nonexistent_returns_none(self, db_session):
        assert crud.clone_benchmark_set(db_session, "fake", "ws1") is None


# ---------------------------------------------------------------------------
# TestRun CRUD
# ---------------------------------------------------------------------------


class TestCreateTestRun:
    def test_create_test_run(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "BS")
        db_session.flush()

        run = crud.create_test_run(
            db_session, bs.id, name="Run 1", total_tests=3,
            avg_correctness=0.8, avg_confidence=1.0,
        )
        assert run.id is not None
        assert run.benchmark_set_id == bs.id
        assert run.total_tests == 3
        assert run.avg_correctness == 0.8


class TestReadTestRun:
    def test_get_test_run_with_results(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "BS")
        run = crud.create_test_run(db_session, bs.id, name="Run 1")
        crud.create_test_results(db_session, run.id, [_make_result_dict()])
        db_session.flush()

        found = crud.get_test_run(db_session, run.id, "ws1")
        assert found is not None
        assert len(found.test_results) == 1

    def test_list_test_runs_by_workspace(self, db_session):
        bs1 = crud.create_benchmark_set(db_session, "ws1", "conn-1", "BS1")
        bs2 = crud.create_benchmark_set(db_session, "ws2", "conn-2", "BS2")
        crud.create_test_run(db_session, bs1.id, name="Run A")
        crud.create_test_run(db_session, bs2.id, name="Run B")
        db_session.flush()

        runs = crud.get_test_runs(db_session, "ws1")
        assert len(runs) == 1
        assert runs[0].name == "Run A"


class TestDeleteTestRun:
    def test_delete_existing(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "BS")
        run = crud.create_test_run(db_session, bs.id, name="Run")
        db_session.flush()

        assert crud.delete_test_run(db_session, run.id, "ws1") is True
        assert crud.get_test_run(db_session, run.id, "ws1") is None

    def test_delete_wrong_workspace(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "BS")
        run = crud.create_test_run(db_session, bs.id, name="Run")
        db_session.flush()

        assert crud.delete_test_run(db_session, run.id, "ws_other") is False


# ---------------------------------------------------------------------------
# Property 6: Round-trip TestResult storage
# ---------------------------------------------------------------------------


class TestRoundTripTestResult:
    def test_all_fields_preserved(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws1", "conn-1", "BS")
        run = crud.create_test_run(db_session, bs.id, name="Run")

        original = _make_result_dict(
            answer="My answer",
            correctness=0.85,
            answer_relevancy=0.72,
            faithfulness=0.91,
            context_precision=0.65,
            context_recall=0.55,
            confidence=1.0,
        )
        rows = crud.create_test_results(db_session, run.id, [original])
        db_session.flush()

        # Re-read from DB
        loaded_run = crud.get_test_run(db_session, run.id, "ws1")
        assert loaded_run is not None
        tr = loaded_run.test_results[0]

        assert tr.actual_answer == "My answer"
        assert tr.correctness == pytest.approx(0.85)
        assert tr.answer_relevancy == pytest.approx(0.72)
        assert tr.faithfulness == pytest.approx(0.91)
        assert tr.context_precision == pytest.approx(0.65)
        assert tr.context_recall == pytest.approx(0.55)
        assert tr.confidence == pytest.approx(1.0)
        assert tr.question == {"text": "Q?"}
        assert tr.claim_scores == [{"claim": "c1", "score": 80}]
        assert tr.context == {"fragments": ["frag1"]}


# ---------------------------------------------------------------------------
# Property 5: Average metrics computation
# ---------------------------------------------------------------------------


class TestAverageMetrics:
    def test_compute_avg_metrics_basic(self):
        r1 = TestResultRow(correctness=0.8, answer_relevancy=0.6,
                           faithfulness=None, context_precision=0.4,
                           context_recall=0.5, confidence=1.0,
                           actual_answer="a", id="1", test_run_id="r")
        r2 = TestResultRow(correctness=0.6, answer_relevancy=0.8,
                           faithfulness=0.9, context_precision=0.6,
                           context_recall=0.7, confidence=1.0,
                           actual_answer="b", id="2", test_run_id="r")

        avg = crud.compute_avg_metrics([r1, r2])

        assert avg["avg_correctness"] == pytest.approx(0.7)
        assert avg["avg_answer_relevancy"] == pytest.approx(0.7)
        # faithfulness: only r2 has a value
        assert avg["avg_faithfulness"] == pytest.approx(0.9)
        assert avg["avg_context_precision"] == pytest.approx(0.5)
        assert avg["avg_context_recall"] == pytest.approx(0.6)
        assert avg["avg_confidence"] == pytest.approx(1.0)

    def test_all_none_returns_none(self):
        r1 = TestResultRow(correctness=None, answer_relevancy=None,
                           faithfulness=None, context_precision=None,
                           context_recall=None, confidence=None,
                           actual_answer="a", id="1", test_run_id="r")

        avg = crud.compute_avg_metrics([r1])

        for key in avg:
            assert avg[key] is None

    def test_empty_list(self):
        avg = crud.compute_avg_metrics([])
        for key in avg:
            assert avg[key] is None


# ---------------------------------------------------------------------------
# Property 7: Workspace isolation
# ---------------------------------------------------------------------------


class TestWorkspaceIsolation:
    def test_benchmark_sets_isolated(self, db_session):
        crud.create_benchmark_set(db_session, "ws_a", "conn-a", "Set A")
        crud.create_benchmark_set(db_session, "ws_b", "conn-b", "Set B")
        db_session.flush()

        sets_a = crud.get_benchmark_sets(db_session, "ws_a")
        sets_b = crud.get_benchmark_sets(db_session, "ws_b")

        assert len(sets_a) == 1
        assert sets_a[0].name == "Set A"
        assert len(sets_b) == 1
        assert sets_b[0].name == "Set B"

    def test_get_benchmark_set_wrong_workspace(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws_a", "conn-a", "Set A")
        db_session.flush()

        assert crud.get_benchmark_set(db_session, bs.id, "ws_b") is None

    def test_test_runs_isolated(self, db_session):
        bs_a = crud.create_benchmark_set(db_session, "ws_a", "conn-a", "A")
        bs_b = crud.create_benchmark_set(db_session, "ws_b", "conn-b", "B")
        crud.create_test_run(db_session, bs_a.id, name="Run A")
        crud.create_test_run(db_session, bs_b.id, name="Run B")
        db_session.flush()

        runs_a = crud.get_test_runs(db_session, "ws_a")
        runs_b = crud.get_test_runs(db_session, "ws_b")

        assert len(runs_a) == 1
        assert runs_a[0].name == "Run A"
        assert len(runs_b) == 1
        assert runs_b[0].name == "Run B"

    def test_delete_benchmark_wrong_workspace_fails(self, db_session):
        bs = crud.create_benchmark_set(db_session, "ws_a", "conn-a", "A")
        db_session.flush()

        assert crud.delete_benchmark_set(db_session, bs.id, "ws_b") is False
        # Still exists in ws_a
        assert crud.get_benchmark_set(db_session, bs.id, "ws_a") is not None
