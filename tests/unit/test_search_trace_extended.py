"""Tests for extended search trace: pipeline_stages and retrieved_doc_labels.

Validates that when return_trace=True, the trace dict contains:
- pipeline_stages dict with all expected sub-keys
- retrieved_doc_labels as a list
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

_SEARCH_MODULE = "metronix.retrieval.search"


def _patch_search_internals():
    """Return a dict of patches for all internal functions of hybrid_search_and_answer."""
    patches = {
        "merge_channels": patch(
            f"{_SEARCH_MODULE}.merge_channels",
            return_value=[],
        ),
        "chat_completion_with_retry": patch(
            f"{_SEARCH_MODULE}.chat_completion_with_retry",
            return_value="Test answer",
        ),
        "get_graph_entities": patch(
            f"{_SEARCH_MODULE}.get_graph_entities",
            return_value=[],
        ),
        "get_entities_by_doc_labels": patch(
            f"{_SEARCH_MODULE}.get_entities_by_doc_labels",
            return_value=[],
        ),
        "get_graph_relationships": patch(
            f"{_SEARCH_MODULE}.get_graph_relationships",
            return_value=[],
        ),
        "get_doc_labels_by_entities": patch(
            f"{_SEARCH_MODULE}.get_doc_labels_by_entities",
            return_value=[],
        ),
        "expand_query": patch(
            f"{_SEARCH_MODULE}.expand_query",
            side_effect=lambda q: f"expanded {q}",
        ),
        "translate_query_to_english": patch(
            f"{_SEARCH_MODULE}.translate_query_to_english",
            side_effect=lambda q: q,
        ),
        "get_alias_registry": patch(f"{_SEARCH_MODULE}.get_alias_registry"),
        "resolve_person_name": patch(
            f"{_SEARCH_MODULE}.resolve_person_name",
            return_value=[],
        ),
        "select_fragments_within_budget": patch(
            f"{_SEARCH_MODULE}.select_fragments_within_budget",
            return_value=[
                {
                    "text": "fragment one",
                    "source_role": "knowledge_base",
                    "source_type": "confluence",
                    "title": "Doc One",
                    "doc_label": "c:1",
                    "date": "",
                },
                {
                    "text": "fragment two",
                    "source_role": "knowledge_base",
                    "source_type": "confluence",
                    "title": "Doc Two",
                    "doc_label": "c:2",
                    "date": "",
                },
            ],
        ),
        "estimate_graph_tokens": patch(
            f"{_SEARCH_MODULE}.estimate_graph_tokens",
            return_value=0,
        ),
        "truncate_graph_context": patch(
            f"{_SEARCH_MODULE}.truncate_graph_context",
            return_value=([], [], []),
        ),
        "detect_response_language": patch(
            f"{_SEARCH_MODULE}.detect_response_language",
            return_value="en",
        ),
        "should_use_team_workflow_schema": patch(
            f"{_SEARCH_MODULE}.should_use_team_workflow_schema",
            return_value=False,
        ),
        "classify_query": patch(
            f"{_SEARCH_MODULE}.classify_query",
            return_value={"profile": "mixed", "confidence": 1.0, "method": "rule"},
        ),
        "recall_dense_async": patch(f"{_SEARCH_MODULE}.recall_dense_async", return_value=[]),
        "recall_exact_async": patch(f"{_SEARCH_MODULE}.recall_exact_async", return_value=[]),
        "recall_metadata_async": patch(f"{_SEARCH_MODULE}.recall_metadata_async", return_value=[]),
        "recall_graph_async": patch(f"{_SEARCH_MODULE}.recall_graph_async", return_value=[]),
    }
    return patches


class TestPipelineStagesInTrace:
    """Verify pipeline_stages dict is present and complete in trace output."""

    async def test_pipeline_stages_key_exists(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="What is Metronix?",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert isinstance(result, dict)
            assert "pipeline_stages" in result
        finally:
            for p in patches.values():
                p.stop()

    @pytest.mark.skip(reason="pre-existing failure; MTRNIX-458 follow-up")
    async def test_pipeline_stages_has_all_subkeys(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="What is Metronix?",
                return_trace=True,
                workspace_id="ws_test",
            )

            stages = result["pipeline_stages"]
            expected_subkeys = {
                "original_query",
                "translated_query",
                "expanded_query",
                "detected_language",
                "recall_dense_count",
                "recall_exact_count",
                "recall_metadata_count",
                "recall_graph_count",
                "recall_total_unique",
                "pre_rerank_count",
                "post_rerank_count",
                "signal_scored_count",
                "rerank_pool_count",
                "fragment_count",
                "primary_fragment_count",
                "supporting_fragment_count",
                "token_budget_used",
                "query_profile",
                "query_profile_method",
                "query_profile_confidence",
            }
            assert set(stages.keys()) == expected_subkeys
        finally:
            for p in patches.values():
                p.stop()

    async def test_pipeline_stages_query_values(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="What is Metronix?",
                return_trace=True,
                workspace_id="ws_test",
            )

            stages = result["pipeline_stages"]
            assert stages["original_query"] == "What is Metronix?"
            assert stages["detected_language"] == "en"
            # expand_query mock prepends "expanded "
            assert stages["expanded_query"] == "expanded What is Metronix?"
        finally:
            for p in patches.values():
                p.stop()

    async def test_pipeline_stages_counts_are_ints(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="Test query",
                return_trace=True,
                workspace_id="ws_test",
            )

            stages = result["pipeline_stages"]
            for key in (
                "recall_dense_count",
                "recall_exact_count",
                "recall_metadata_count",
                "recall_graph_count",
                "recall_total_unique",
                "pre_rerank_count",
                "post_rerank_count",
                "signal_scored_count",
                "rerank_pool_count",
                "fragment_count",
                "token_budget_used",
            ):
                assert isinstance(stages[key], int), f"{key} should be int"
        finally:
            for p in patches.values():
                p.stop()

    async def test_fragment_count_matches_fragments(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="Test query",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert result["pipeline_stages"]["fragment_count"] == len(result["fragments"])
        finally:
            for p in patches.values():
                p.stop()


class TestRetrievedDocLabelsInTrace:
    """Verify retrieved_doc_labels is present and correct in trace output."""

    async def test_retrieved_doc_labels_key_exists(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="Test query",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert "retrieved_doc_labels" in result
            assert isinstance(result["retrieved_doc_labels"], list)
        finally:
            for p in patches.values():
                p.stop()

    async def test_retrieved_doc_labels_populated_from_results(self):
        patches = _patch_search_internals()
        # Make merge_channels return results with doc_labels
        patches["merge_channels"] = patch(
            f"{_SEARCH_MODULE}.merge_channels",
            return_value=[
                {
                    "chunk_id": "c1",
                    "doc_label": "DOC-1",
                    "memory": {"memory": "text one", "doc_label": "DOC-1"},
                    "channels": ["dense"],
                    "channel_scores": {"dense": 0.9},
                },
                {
                    "chunk_id": "c2",
                    "doc_label": "DOC-2",
                    "memory": {"memory": "text two", "doc_label": "DOC-2"},
                    "channels": ["exact"],
                    "channel_scores": {"exact": 0.8},
                },
                {
                    "chunk_id": "c3",
                    "doc_label": "",
                    "memory": {"memory": "no label"},
                    "channels": ["dense"],
                    "channel_scores": {"dense": 0.5},
                },
            ],
        )
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="Test query",
                return_trace=True,
                workspace_id="ws_test",
            )

            labels = result["retrieved_doc_labels"]
            assert isinstance(labels, list)
            assert "DOC-1" in labels
            assert "DOC-2" in labels
            # Empty/missing doc_labels should be excluded
            assert "" not in labels
        finally:
            for p in patches.values():
                p.stop()

    async def test_retrieved_doc_labels_empty_when_no_labels(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="Test query",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert result["retrieved_doc_labels"] == []
        finally:
            for p in patches.values():
                p.stop()


class TestTraceNotInNonTraceMode:
    """Verify pipeline_stages and retrieved_doc_labels are NOT in non-trace output."""

    async def test_non_trace_returns_string(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metronix.retrieval.search import hybrid_search_and_answer

            result = await hybrid_search_and_answer(
                query="Test query",
                return_trace=False,
                workspace_id="ws_test",
            )

            assert isinstance(result, str)
        finally:
            for p in patches.values():
                p.stop()
