"""Tests for retrieval/token_budget.py — token estimation and fragment selection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.retrieval.token_budget import (
    MAX_GRAPH_TOKENS,
    MIN_FRAGMENT_TOKENS,
    estimate_graph_tokens,
    estimate_tokens,
    select_fragments_within_budget,
    truncate_graph_context,
)


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_english_text(self) -> None:
        """English text: ~4 chars per token."""
        text = "Hello world, this is a test."  # 28 chars
        tokens = estimate_tokens(text)
        assert tokens == 28 // 4  # 7

    def test_russian_text(self) -> None:
        """Russian text: ~2 chars per token."""
        text = "Привет мир"  # 10 chars, all Cyrillic (9 letters + 1 space)
        tokens = estimate_tokens(text)
        # 9 Cyrillic chars → 9 // 2 = 4, 1 space (other) → 1 // 4 = 0
        assert tokens == 4

    def test_mixed_text(self) -> None:
        """Mixed English + Russian text."""
        text = "Hello Привет"  # 6 latin + 1 space + 6 cyrillic = 12 chars
        tokens = estimate_tokens(text)
        # 7 other chars → 7 // 4 = 1, 6 cyrillic → 6 // 2 = 3
        assert tokens == 4

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_none_like_empty(self) -> None:
        assert estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# select_fragments_within_budget
# ---------------------------------------------------------------------------

class TestSelectFragmentsWithinBudget:
    def test_all_fit(self) -> None:
        """When all fragments fit within budget, all are returned."""
        frags = ["short frag one", "short frag two", "short frag three"]
        result = select_fragments_within_budget(
            frags, max_tokens=6000, answer_reserve_tokens=500,
        )
        assert result == frags

    def test_budget_exceeded(self) -> None:
        """When budget is tight, only first N fragments are returned."""
        # Each fragment ~500 tokens (2000 chars / 4)
        frags = ["A" * 2000 for _ in range(10)]
        result = select_fragments_within_budget(
            frags, max_tokens=4000, system_prompt_tokens=500,
            answer_reserve_tokens=500,
        )
        # Budget = 4000 - 500 - 500 = 3000 tokens (above MIN floor) → 6 fragments fit
        assert len(result) == 6

    def test_single_huge_fragment_truncated(self) -> None:
        """A single fragment exceeding budget gets truncated."""
        huge = "B" * 40000  # ~10000 tokens
        result = select_fragments_within_budget(
            [huge], max_tokens=2000, system_prompt_tokens=500,
            answer_reserve_tokens=500,
        )
        assert len(result) == 1
        assert len(result[0]) < len(huge)

    def test_empty_list(self) -> None:
        result = select_fragments_within_budget([])
        assert result == []

    def test_respects_answer_reserve(self) -> None:
        """Higher answer reserve → fewer fragments fit."""
        frag = "C" * 12000  # ~3000 tokens
        # Low reserve: budget = 5000 - 500 - 500 = 4000 → fits (3000 < 4000)
        result_low = select_fragments_within_budget(
            [frag], max_tokens=5000, system_prompt_tokens=500,
            answer_reserve_tokens=500,
        )
        assert len(result_low) == 1
        assert result_low[0] == frag

        # High reserve: computed = 5000 - 500 - 4000 = 500, floored to 2000
        # but 3000 > 2000 → truncated
        result_high = select_fragments_within_budget(
            [frag], max_tokens=5000, system_prompt_tokens=500,
            answer_reserve_tokens=4000,
        )
        assert len(result_high) == 1
        assert len(result_high[0]) < len(frag)

    def test_graph_tokens_reduce_fragment_budget(self) -> None:
        """Graph context tokens reduce the space available for fragments."""
        frag = "D" * 12000  # ~3000 tokens
        # No graph: budget = 5000 - 500 - 500 = 4000 → fits (3000 < 4000)
        result_no_graph = select_fragments_within_budget(
            [frag], max_tokens=5000, system_prompt_tokens=500,
            answer_reserve_tokens=500, graph_tokens=0,
        )
        assert len(result_no_graph) == 1
        assert result_no_graph[0] == frag

        # With large graph: computed = 5000 - 500 - 500 - 3000 = 1000,
        # floored to 2000 but 3000 > 2000 → truncated
        result_with_graph = select_fragments_within_budget(
            [frag], max_tokens=5000, system_prompt_tokens=500,
            answer_reserve_tokens=500, graph_tokens=3000,
        )
        assert len(result_with_graph) == 1
        assert len(result_with_graph[0]) < len(frag)


# ---------------------------------------------------------------------------
# estimate_graph_tokens
# ---------------------------------------------------------------------------

class TestEstimateGraphTokens:
    def test_empty_graph(self) -> None:
        tokens = estimate_graph_tokens([], [], [])
        # Even empty JSON has some chars: {"entities":[],"relationships":[],"documents":[]}
        assert tokens > 0
        assert tokens < 50

    def test_graph_with_data(self) -> None:
        ents = [{"name": "Qdrant", "type": "Technology"}]
        rels = [{"source": "Alice", "target": "Qdrant", "type": "uses"}]
        docs = [{"doc_label": "DOC-1"}]
        tokens = estimate_graph_tokens(ents, rels, docs)
        assert tokens > 20


# ---------------------------------------------------------------------------
# Integration: search pipeline uses token budget
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# truncate_graph_context
# ---------------------------------------------------------------------------

class TestTruncateGraphContext:
    def test_large_graph_gets_truncated(self) -> None:
        """Graph exceeding MAX_GRAPH_TOKENS is truncated."""
        # Build a graph that's clearly over 2000 tokens
        g_ents = [{"name": f"Entity-{i}", "type": "Technology"} for i in range(200)]
        g_rels = [{"source": f"Entity-{i}", "target": f"Entity-{i+1}", "type": "uses"}
                  for i in range(199)]
        g_docs = [{"doc_label": f"DOC-{i}"} for i in range(100)]

        original_tokens = estimate_graph_tokens(g_ents, g_rels, g_docs)
        assert original_tokens > MAX_GRAPH_TOKENS

        t_ents, t_rels, t_docs = truncate_graph_context(g_ents, g_rels, g_docs)
        truncated_tokens = estimate_graph_tokens(t_ents, t_rels, t_docs)
        assert truncated_tokens <= MAX_GRAPH_TOKENS
        assert len(t_ents) < len(g_ents)

    def test_person_entities_preserved(self) -> None:
        """Person entities are kept with priority during truncation."""
        persons = [{"name": f"Person-{i}", "type": "Person"} for i in range(5)]
        others = [{"name": f"Tech-{i}", "type": "Technology"} for i in range(200)]
        g_ents = persons + others
        g_rels = []
        g_docs = []

        t_ents, _, _ = truncate_graph_context(g_ents, g_rels, g_docs, max_tokens=500)

        kept_persons = [e for e in t_ents if e["type"] == "Person"]
        assert len(kept_persons) == 5

    def test_small_graph_unchanged(self) -> None:
        """Graph under MAX_GRAPH_TOKENS passes through unchanged."""
        g_ents = [{"name": "Qdrant", "type": "Technology"}]
        g_rels = [{"source": "Alice", "target": "Qdrant", "type": "uses"}]
        g_docs = [{"doc_label": "DOC-1"}]

        assert estimate_graph_tokens(g_ents, g_rels, g_docs) < MAX_GRAPH_TOKENS
        # truncate_graph_context still works but should keep everything
        t_ents, t_rels, t_docs = truncate_graph_context(g_ents, g_rels, g_docs)
        assert len(t_ents) == 1
        assert len(t_rels) == 1
        assert len(t_docs) == 1


class TestMinFragmentBudget:
    def test_fragments_get_minimum_even_with_huge_graph(self) -> None:
        """Fragments always get MIN_FRAGMENT_TOKENS even if graph is large."""
        # Fragment that needs ~1000 tokens (4000 chars)
        frag = "F" * 4000
        # Graph claims all budget: max=3000, prompt=500, reserve=500, graph=2500
        # computed = 3000 - 500 - 500 - 2500 = -500 → but min floor = 2000
        result = select_fragments_within_budget(
            [frag], max_tokens=3000, system_prompt_tokens=500,
            answer_reserve_tokens=500, graph_tokens=2500,
        )
        # Fragment fits within MIN_FRAGMENT_TOKENS (2000 > 1000)
        assert len(result) == 1
        assert result[0] == frag

    def test_min_floor_value(self) -> None:
        assert MIN_FRAGMENT_TOKENS == 2000


class TestDefaultBudget:
    def test_default_max_tokens_is_10000(self) -> None:
        from metatron.core.config import Settings
        s = Settings()
        assert s.llm_context_max_tokens == 10000


# ---------------------------------------------------------------------------
# Integration: search pipeline uses token budget
# ---------------------------------------------------------------------------

class TestSearchPipelineIntegration:
    @patch("metatron.retrieval.search.chat_completion_with_retry")
    @patch("metatron.retrieval.search.recall_graph", return_value=[])
    @patch("metatron.retrieval.search.recall_metadata", return_value=[])
    @patch("metatron.retrieval.search.recall_exact", return_value=[])
    @patch("metatron.retrieval.search.recall_dense")
    @patch("metatron.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metatron.retrieval.search.get_entities_by_doc_labels", return_value=[])
    def test_token_budget_applied_before_llm_call(
        self,
        mock_graph_ents: MagicMock,
        mock_expand: MagicMock,
        mock_dense: MagicMock,
        _mock_exact: MagicMock,
        _mock_metadata: MagicMock,
        _mock_graph: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        """Token budget limits fragments passed to _build_ctx."""
        # Return many large results via dense channel
        mock_dense.return_value = [
            {"chunk_id": f"c{i}", "doc_label": f"DOC-{i}", "score": 0.9,
             "memory": {"memory": "X" * 8000, "type": "jira", "title": f"Issue-{i}",
                        "doc_label": f"DOC-{i}"}}
            for i in range(20)
        ]
        mock_llm.return_value = "Test answer"

        from metatron.retrieval.search import hybrid_search_and_answer

        with patch("metatron.retrieval.search._s") as mock_settings:
            mock_settings.search_max_total_chars = 400000
            mock_settings.search_max_fragment_chars = 8000
            mock_settings.search_pool_multiplier = 3
            mock_settings.search_pool_min = 15
            mock_settings.llm_context_max_tokens = 3000
            mock_settings.llm_answer_reserve_tokens = 1500

            hybrid_search_and_answer("test query", workspace_id="TEST")

        # LLM was called
        mock_llm.assert_called_once()
        # The user content passed to LLM should be bounded
        call_messages = mock_llm.call_args.kwargs.get("messages") or mock_llm.call_args[1].get("messages")
        user_content = call_messages[-1]["content"]
        # With 3000 max tokens and 1500 answer reserve, ~1000 tokens for fragments
        # That's roughly ~4000 chars — far less than 20 * 8000 = 160000
        assert len(user_content) < 20000
