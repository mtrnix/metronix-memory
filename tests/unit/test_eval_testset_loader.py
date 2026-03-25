"""Tests for eval test set YAML loader and validation."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

if "benchmark_qed" not in sys.modules:
    _mock = MagicMock()
    for _name in [
        "benchmark_qed",
        "benchmark_qed.autoe",
        "benchmark_qed.autoe.assertion_scores",
        "benchmark_qed.autod",
        "benchmark_qed.autod.data_model",
        "benchmark_qed.autod.data_model.text_unit",
        "benchmark_qed.autod.data_processor",
        "benchmark_qed.autod.data_processor.embedding",
        "benchmark_qed.autod.sampler",
        "benchmark_qed.autod.sampler.clustering",
        "benchmark_qed.autod.sampler.clustering.kmeans",
        "benchmark_qed.autoq",
        "benchmark_qed.autoq.data_model",
        "benchmark_qed.autoq.data_model.question",
        "benchmark_qed.autoq.question_gen",
        "benchmark_qed.autoq.question_gen.data_questions",
        "benchmark_qed.autoq.question_gen.data_questions.global_question_gen",
        "benchmark_qed.autoq.question_gen.data_questions.local_question_gen",
        "benchmark_qed.autoq.question_generator",
        "benchmark_qed.config",
        "benchmark_qed.config.llm_config",
        "benchmark_qed.llm",
        "benchmark_qed.llm.provider",
        "benchmark_qed.llm.provider.openai",
    ]:
        sys.modules[_name] = _mock

import pytest
import yaml

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
        negative_categories = {"negative/no-data", "negative/greeting", "vague"}
        for q in ts.queries:
            assert q.text, f"Query {q.id} has empty text"
            if q.category in negative_categories:
                assert len(q.expected_doc_labels) == 0, (
                    f"Negative query {q.id} should have empty expected_doc_labels"
                )
            else:
                assert len(q.expected_doc_labels) >= 1, (
                    f"Query {q.id} has no expected_doc_labels"
                )


# ---------------------------------------------------------------------------
# Negative / edge cases
# ---------------------------------------------------------------------------


class TestLoadEvalTestsetNegativeCases:
    def test_invalid_yaml_syntax(self) -> None:
        yaml_str = "queries:\n  - id: [unterminated"
        with pytest.raises(yaml.YAMLError):
            load_eval_testset(yaml_str)

    def test_yaml_not_a_dict(self) -> None:
        yaml_str = "- item1\n- item2\n"
        with pytest.raises((AttributeError, TypeError)):
            load_eval_testset(yaml_str)

    def test_query_with_whitespace_only_text(self) -> None:
        yaml_str = """
queries:
  - id: "q1"
    text: "   "
    expected_doc_labels: ["a:1"]
"""
        # The loader does not strip text — it should load but text is whitespace
        ts = load_eval_testset(yaml_str)
        assert ts.queries[0].text == "   "

    def test_query_with_empty_expected_doc_labels(self) -> None:
        yaml_str = """
queries:
  - id: "q1"
    text: "question"
    expected_doc_labels: []
"""
        # from_dict converts to set([]) which is empty — loader allows it
        ts = load_eval_testset(yaml_str)
        assert len(ts.queries[0].expected_doc_labels) == 0

    def test_query_with_non_string_doc_labels(self) -> None:
        yaml_str = """
queries:
  - id: "q1"
    text: "question"
    expected_doc_labels: [123, 456]
"""
        ts = load_eval_testset(yaml_str)
        assert 123 in ts.queries[0].expected_doc_labels

    def test_large_test_set_loads(self) -> None:
        queries = "\n".join(
            f'  - id: "q{i}"\n    text: "question {i}"\n    expected_doc_labels: ["doc:{i}"]'
            for i in range(150)
        )
        yaml_str = f"queries:\n{queries}\n"
        ts = load_eval_testset(yaml_str)
        assert len(ts.queries) == 150

    def test_version_missing_defaults_to_1_0(self) -> None:
        yaml_str = """
queries:
  - id: "q1"
    text: "question"
    expected_doc_labels: ["a:1"]
"""
        ts = load_eval_testset(yaml_str)
        assert ts.version == "1.0"

    def test_description_missing_defaults_to_empty(self) -> None:
        yaml_str = """
queries:
  - id: "q1"
    text: "question"
    expected_doc_labels: ["a:1"]
"""
        ts = load_eval_testset(yaml_str)
        assert ts.description == ""

    def test_extra_unknown_fields_in_query_no_error(self) -> None:
        yaml_str = """
queries:
  - id: "q1"
    text: "question"
    expected_doc_labels: ["a:1"]
    unknown_field: "should be ignored"
    another_extra: 42
"""
        ts = load_eval_testset(yaml_str)
        assert ts.queries[0].id == "q1"

    def test_path_does_not_exist_raises(self, tmp_path) -> None:
        bad_path = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            load_eval_testset_from_path(bad_path)
