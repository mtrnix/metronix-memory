"""Tests for diversify_results(), _collect_frags() source labeling, and search utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.retrieval.search import (
    diversify_results, _collect_frags, _result_type, _append_sources,
    detect_response_language, search_with_date_filter,
)


class TestResultType:
    def test_from_type_field(self) -> None:
        assert _result_type({"type": "jira"}) == "jira"

    def test_from_payload(self) -> None:
        assert _result_type({"payload": {"type": "confluence"}}) == "confluence"

    def test_from_metadata(self) -> None:
        assert _result_type({"metadata": {"type": "jira"}}) == "jira"

    def test_unknown_fallback(self) -> None:
        assert _result_type({}) == "unknown"

    def test_case_normalized(self) -> None:
        assert _result_type({"type": "JIRA"}) == "jira"


class TestDiversifyResults:
    def test_includes_both_sources(self) -> None:
        results = [
            {"memory": "jira1", "type": "jira", "score": 0.9},
            {"memory": "jira2", "type": "jira", "score": 0.85},
            {"memory": "jira3", "type": "jira", "score": 0.8},
            {"memory": "conf1", "type": "confluence", "score": 0.7},
            {"memory": "conf2", "type": "confluence", "score": 0.6},
        ]
        diversified = diversify_results(results, k=4)
        types = {_result_type(r) for r in diversified}
        assert "jira" in types
        assert "confluence" in types

    def test_min_per_source(self) -> None:
        results = [
            {"memory": "j1", "type": "jira", "score": 0.9},
            {"memory": "j2", "type": "jira", "score": 0.8},
            {"memory": "j3", "type": "jira", "score": 0.7},
            {"memory": "c1", "type": "confluence", "score": 0.6},
        ]
        diversified = diversify_results(results, k=3)
        types = [_result_type(r) for r in diversified]
        assert "confluence" in types

    def test_single_source_unchanged(self) -> None:
        results = [
            {"memory": "j1", "type": "jira", "score": 0.9},
            {"memory": "j2", "type": "jira", "score": 0.8},
        ]
        diversified = diversify_results(results, k=5)
        assert len(diversified) == 2

    def test_empty(self) -> None:
        assert diversify_results([], k=5) == []

    def test_respects_k_limit(self) -> None:
        results = [
            {"memory": f"item{i}", "type": "jira" if i % 2 == 0 else "confluence", "score": 1.0 - i * 0.1}
            for i in range(10)
        ]
        diversified = diversify_results(results, k=4)
        assert len(diversified) == 4

    def test_three_sources(self) -> None:
        results = [
            {"memory": "j1", "type": "jira", "score": 0.9},
            {"memory": "j2", "type": "jira", "score": 0.8},
            {"memory": "c1", "type": "confluence", "score": 0.7},
            {"memory": "c2", "type": "confluence", "score": 0.6},
            {"memory": "g1", "type": "github", "score": 0.5},
        ]
        diversified = diversify_results(results, k=5)
        types = {_result_type(r) for r in diversified}
        assert types == {"jira", "confluence", "github"}

    def test_k_zero(self) -> None:
        results = [{"memory": "x", "type": "jira", "score": 1.0}]
        assert diversify_results(results, k=0) == []

    def test_fills_remaining_by_score(self) -> None:
        results = [
            {"memory": "j1", "type": "jira", "score": 0.9},
            {"memory": "j2", "type": "jira", "score": 0.85},
            {"memory": "j3", "type": "jira", "score": 0.5},
            {"memory": "c1", "type": "confluence", "score": 0.8},
            {"memory": "c2", "type": "confluence", "score": 0.3},
        ]
        # k=5: 2 jira + 2 confluence reserved, 1 remaining slot
        diversified = diversify_results(results, k=5)
        assert len(diversified) == 5
        # The remaining slot should go to j3 (0.5) over c2 (0.3)
        memories = [r["memory"] for r in diversified]
        assert "j3" in memories


class TestCollectFragsLabeling:
    def test_labels_added(self) -> None:
        base = [
            {"memory": "some jira content", "type": "jira", "title": "MTRNIX-78"},
            {"memory": "some confluence page", "type": "confluence", "title": "Architecture"},
        ]
        frags, _, _ = _collect_frags(base, set(), 0)
        assert len(frags) == 2
        assert frags[0].startswith("[JIRA] MTRNIX-78\n")
        assert frags[1].startswith("[CONFLUENCE] Architecture\n")

    def test_no_label_for_unknown(self) -> None:
        base = [{"memory": "plain text"}]
        frags, _, _ = _collect_frags(base, set(), 0)
        assert len(frags) == 1
        assert not frags[0].startswith("[")

    def test_label_with_payload_type(self) -> None:
        base = [{"memory": "content", "payload": {"type": "jira", "title": "Issue"}}]
        frags, _, _ = _collect_frags(base, set(), 0)
        assert "[JIRA]" in frags[0]


class TestAppendSources:
    def test_appends_sources(self) -> None:
        results = [
            {"title": "2026-02-03 Summary", "type": "confluence"},
            {"title": "[MTRNIX-109] Setup MLFlow", "type": "jira"},
        ]
        out = _append_sources("Some answer.", results)
        assert "\U0001f4da Sources:" in out
        assert "\U0001f4c4 2026-02-03 Summary" in out
        assert "\U0001f4cb [MTRNIX-109] Setup MLFlow" in out

    def test_no_sources_when_empty(self) -> None:
        assert _append_sources("Answer.", []) == "Answer."

    def test_no_sources_when_no_titles(self) -> None:
        results = [{"memory": "text", "type": "jira"}]
        assert _append_sources("Answer.", results) == "Answer."

    def test_deduplicates_titles(self) -> None:
        results = [
            {"title": "Same Page", "type": "confluence"},
            {"title": "Same Page", "type": "confluence"},
            {"title": "Other Page", "type": "confluence"},
        ]
        out = _append_sources("Answer.", results)
        assert out.count("Same Page") == 1
        assert "Other Page" in out

    def test_max_five_sources(self) -> None:
        results = [{"title": f"Page {i}", "type": "confluence"} for i in range(10)]
        out = _append_sources("Answer.", results)
        lines = out.split("\U0001f4da Sources:\n")[1].strip().split("\n")
        assert len(lines) == 5

    def test_title_from_payload(self) -> None:
        results = [{"payload": {"title": "From Payload", "type": "jira"}}]
        out = _append_sources("Answer.", results)
        assert "From Payload" in out

    def test_preserves_answer(self) -> None:
        results = [{"title": "Page", "type": "confluence"}]
        out = _append_sources("My detailed answer here.", results)
        assert out.startswith("My detailed answer here.")


class TestDetectResponseLanguage:
    def test_english_query(self) -> None:
        assert detect_response_language("What the team doing this week?") == "English"

    def test_russian_query(self) -> None:
        assert detect_response_language("Что делает команда на этой неделе?") == "Russian"

    def test_english_not_affected_by_single_russian_word(self) -> None:
        assert detect_response_language("What about задача MTRNIX-123?") == "English"

    def test_pure_english_after_russian_history_not_mixed(self) -> None:
        """Language detection must use only the current question, not composite."""
        # This is the actual question — no Russian in it
        assert detect_response_language("What the team doing this week?") == "English"


class TestDateWidening:
    @patch("metatron.retrieval.search.get_hybrid_store")
    def test_widens_date_range_when_exact_empty(self, mock_get_store) -> None:
        """When exact date range returns nothing, wider range results are used."""
        store = MagicMock()
        mock_get_store.return_value = store
        # First call (exact range): no results
        # Second call (wider ±7 days): has results
        store.search_by_date.side_effect = [
            [],  # exact range empty
            [{"memory": "recent activity", "date": "2026-02-05", "type": "jira"}],  # wider range
        ]
        store.hybrid_search.return_value = []

        result = search_with_date_filter("what happened this week", k=5)
        assert len(result) >= 1
        assert result[0]["memory"] == "recent activity"
        # search_by_date called twice: exact then wider
        assert store.search_by_date.call_count == 2

    @patch("metatron.retrieval.search.get_hybrid_store")
    def test_wider_range_always_merged(self, mock_get_store) -> None:
        """Even when exact range has results, wider range is merged for diversity."""
        store = MagicMock()
        mock_get_store.return_value = store
        # First call (exact): confluence pages
        # Second call (wider): includes nearby jira issues
        store.search_by_date.side_effect = [
            [{"memory": "conf page", "date": "2026-02-10", "type": "confluence"}],
            [
                {"memory": "conf page", "date": "2026-02-10", "type": "confluence"},
                {"memory": "jira task", "date": "2026-02-05", "type": "jira"},
            ],
        ]
        store.hybrid_search.return_value = []

        result = search_with_date_filter("what happened this week", k=5)
        # Both exact and wider results present
        memories = [r["memory"] for r in result]
        assert "conf page" in memories
        assert "jira task" in memories
        assert store.search_by_date.call_count == 2
