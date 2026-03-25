"""Tests for eval test set YAML loader and validation."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

if "benchmark_qed" not in sys.modules:
    sys.modules["benchmark_qed"] = MagicMock()
    sys.modules["benchmark_qed.auto_e"] = MagicMock()

import pytest

from metatron.benchmarker.services.eval_loader import (
    DEFAULT_TESTSET_PATH,
    EvalQuery,
    load_eval_testset,
    load_eval_testset_from_path,
)

# ---------------------------------------------------------------------------
# EvalQuery.from_dict
# ---------------------------------------------------------------------------


class TestEvalQueryFromDict:
    def test_creates_instance_with_all_fields(self) -> None:
        data = {
            "id": "q-01",
            "text": "What is X?",
            "expected_doc_labels": ["jira:X-1", "confluence:x-doc"],
            "category": "mixed",
            "notes": "some note",
        }
        q = EvalQuery.from_dict(data)
        assert q.id == "q-01"
        assert q.text == "What is X?"
        assert q.expected_doc_labels == {"jira:X-1", "confluence:x-doc"}
        assert q.category == "mixed"
        assert q.notes == "some note"

    def test_defaults_category_and_notes(self) -> None:
        data = {
            "id": "q-02",
            "text": "Where is Y?",
            "expected_doc_labels": ["upload:y-file"],
        }
        q = EvalQuery.from_dict(data)
        assert q.category == "mixed"
        assert q.notes is None

    def test_missing_id_raises(self) -> None:
        data = {"text": "hi", "expected_doc_labels": ["a:b"]}
        with pytest.raises(ValueError, match="id"):
            EvalQuery.from_dict(data)

    def test_missing_text_raises(self) -> None:
        data = {"id": "q", "expected_doc_labels": ["a:b"]}
        with pytest.raises(ValueError, match="text"):
            EvalQuery.from_dict(data)

    def test_missing_expected_doc_labels_raises(self) -> None:
        data = {"id": "q", "text": "hi"}
        with pytest.raises(ValueError, match="expected_doc_labels"):
            EvalQuery.from_dict(data)


# ---------------------------------------------------------------------------
# load_eval_testset (YAML string)
# ---------------------------------------------------------------------------


class TestLoadEvalTestset:
    def test_parses_valid_yaml(self) -> None:
        yaml_str = """
version: "2.0"
description: "test desc"
queries:
  - id: "a"
    text: "question a"
    expected_doc_labels:
      - "jira:A-1"
  - id: "b"
    text: "question b"
    expected_doc_labels:
      - "confluence:b-doc"
"""
        ts = load_eval_testset(yaml_str)
        assert ts.version == "2.0"
        assert ts.description == "test desc"
        assert len(ts.queries) == 2
        assert ts.queries[0].id == "a"

    def test_empty_queries_raises(self) -> None:
        yaml_str = """
queries: []
"""
        with pytest.raises(ValueError, match="at least 1"):
            load_eval_testset(yaml_str)

    def test_missing_queries_key_raises(self) -> None:
        yaml_str = """
version: "1.0"
"""
        with pytest.raises(ValueError, match="at least 1"):
            load_eval_testset(yaml_str)

    def test_duplicate_ids_raises(self) -> None:
        yaml_str = """
queries:
  - id: "dup"
    text: "first"
    expected_doc_labels: ["a:1"]
  - id: "dup"
    text: "second"
    expected_doc_labels: ["a:2"]
"""
        with pytest.raises(ValueError, match="Duplicate"):
            load_eval_testset(yaml_str)


# ---------------------------------------------------------------------------
# DEFAULT_TESTSET_PATH and load_eval_testset_from_path
# ---------------------------------------------------------------------------


class TestDefaultTestset:
    def test_default_path_exists(self) -> None:
        assert DEFAULT_TESTSET_PATH.exists(), (
            f"Default test set not found at {DEFAULT_TESTSET_PATH}"
        )

    def test_default_testset_has_16_queries(self) -> None:
        ts = load_eval_testset_from_path(DEFAULT_TESTSET_PATH)
        assert len(ts.queries) >= 16

    def test_all_queries_have_text_and_labels(self) -> None:
        ts = load_eval_testset_from_path(DEFAULT_TESTSET_PATH)
        for q in ts.queries:
            assert q.text, f"Query {q.id} has empty text"
            assert len(q.expected_doc_labels) >= 1, (
                f"Query {q.id} has no expected_doc_labels"
            )
