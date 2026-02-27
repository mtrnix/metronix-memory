"""Tests for hybrid_search_and_answer return_trace parameter.

Validates:
- Property 3: return_trace=True returns dict with all 6 keys
- Property 4: return_trace=False (or omitted) returns str
- Backward compatibility: without return_trace parameter returns str
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# We mock all internal functions so the test doesn't need real services.
_SEARCH_MODULE = "metatron.retrieval.search"


def _patch_search_internals():
    """Return a dict of patches for all internal functions of hybrid_search_and_answer."""
    patches = {
        "get_hybrid_store": patch(f"{_SEARCH_MODULE}.get_hybrid_store"),
        "search_with_date_filter": patch(f"{_SEARCH_MODULE}.search_with_date_filter", return_value=[]),
        "diversify_results": patch(f"{_SEARCH_MODULE}.diversify_results", return_value=[]),
        "chat_completion_with_retry": patch(f"{_SEARCH_MODULE}.chat_completion_with_retry", return_value="Test answer"),
        "get_graph_entities": patch(f"{_SEARCH_MODULE}.get_graph_entities", return_value=[]),
        "get_entities_by_doc_labels": patch(f"{_SEARCH_MODULE}.get_entities_by_doc_labels", return_value=[]),
        "get_graph_relationships": patch(f"{_SEARCH_MODULE}.get_graph_relationships", return_value=[]),
        "get_related_documents": patch(f"{_SEARCH_MODULE}.get_related_documents", return_value=[]),
        "get_doc_labels_by_entities": patch(f"{_SEARCH_MODULE}.get_doc_labels_by_entities", return_value=[]),
        "expand_query": patch(f"{_SEARCH_MODULE}.expand_query", side_effect=lambda q: q),
        "translate_query_to_english": patch(f"{_SEARCH_MODULE}.translate_query_to_english", side_effect=lambda q: q),
        "get_alias_registry": patch(f"{_SEARCH_MODULE}.get_alias_registry"),
        "resolve_person_name": patch(f"{_SEARCH_MODULE}.resolve_person_name", return_value=[]),
        "select_fragments_within_budget": patch(f"{_SEARCH_MODULE}.select_fragments_within_budget", return_value=[]),
        "estimate_graph_tokens": patch(f"{_SEARCH_MODULE}.estimate_graph_tokens", return_value=0),
        "truncate_graph_context": patch(f"{_SEARCH_MODULE}.truncate_graph_context", return_value=([], [], [])),
        "detect_response_language": patch(f"{_SEARCH_MODULE}.detect_response_language", return_value="en"),
        "should_use_team_workflow_schema": patch(f"{_SEARCH_MODULE}.should_use_team_workflow_schema", return_value=False),
    }
    return patches


class TestReturnTraceTrue:
    """Property 3: return_trace=True returns dict with all 6 keys."""

    def test_returns_dict_with_all_keys(self):
        patches = _patch_search_internals()
        mocks = {}
        for name, p in patches.items():
            mocks[name] = p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            result = hybrid_search_and_answer(
                query="What is Metatron?",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert isinstance(result, dict)
            expected_keys = {
                "answer", "source_results", "fragments",
                "graph_entities", "graph_relations", "graph_docs",
            }
            assert set(result.keys()) == expected_keys
        finally:
            for p in patches.values():
                p.stop()

    def test_answer_key_is_string(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            result = hybrid_search_and_answer(
                query="Test question",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert isinstance(result["answer"], str)
        finally:
            for p in patches.values():
                p.stop()

    def test_source_results_is_list(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            result = hybrid_search_and_answer(
                query="Test question",
                return_trace=True,
                workspace_id="ws_test",
            )

            assert isinstance(result["source_results"], list)
            assert isinstance(result["fragments"], list)
            assert isinstance(result["graph_entities"], list)
            assert isinstance(result["graph_relations"], list)
            assert isinstance(result["graph_docs"], list)
        finally:
            for p in patches.values():
                p.stop()


class TestReturnTraceFalse:
    """Property 4: return_trace=False returns str."""

    def test_returns_string(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            result = hybrid_search_and_answer(
                query="What is Metatron?",
                return_trace=False,
                workspace_id="ws_test",
            )

            assert isinstance(result, str)
        finally:
            for p in patches.values():
                p.stop()


class TestBackwardCompatibility:
    """Without return_trace parameter, function returns str (default behavior)."""

    def test_default_returns_string(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            result = hybrid_search_and_answer(
                query="What is Metatron?",
                workspace_id="ws_test",
            )

            assert isinstance(result, str)
        finally:
            for p in patches.values():
                p.stop()

    def test_explicit_false_same_as_default(self):
        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            result_default = hybrid_search_and_answer(
                query="Test", workspace_id="ws_test",
            )
            result_false = hybrid_search_and_answer(
                query="Test", workspace_id="ws_test", return_trace=False,
            )

            assert type(result_default) is type(result_false)
            assert isinstance(result_default, str)
        finally:
            for p in patches.values():
                p.stop()
