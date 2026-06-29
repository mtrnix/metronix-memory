"""Tests for follow-up detection in SessionManager."""

from __future__ import annotations

from metronix.agent.sessions import SessionManager


class TestIsFollowUp:
    def test_pronoun_follow_ups(self) -> None:
        """Queries with pronouns referencing prior context are follow-ups."""
        queries = [
            "What are their deadlines?",
            "Tell me more about it",
            "How is he doing?",
            "А что у них со сроками?",
            "Расскажи про это подробнее",
            "Какой у него статус?",
        ]
        for q in queries:
            assert SessionManager._is_follow_up(q), f"Should be follow-up: {q}"

    def test_continuation_follow_ups(self) -> None:
        """Queries with continuation words are follow-ups."""
        queries = [
            "Also what about testing?",
            "And what about the backend?",
            "How about performance?",
            "А что насчёт тестирования?",
            "Ещё покажи задачи по бэкенду",
        ]
        for q in queries:
            assert SessionManager._is_follow_up(q), f"Should be follow-up: {q}"

    def test_short_queries_are_follow_ups(self) -> None:
        """Very short queries (<=3 words) are treated as follow-ups."""
        queries = [
            "and deadlines?",
            "а сроки?",
            "more details",
        ]
        for q in queries:
            assert SessionManager._is_follow_up(q), f"Should be follow-up: {q}"

    def test_independent_queries(self) -> None:
        """Self-contained questions without pronouns are NOT follow-ups."""
        queries = [
            "What is the team doing this week?",
            "Что делает команда на этой неделе?",
            "Show me all Jira tasks for sprint 5",
            "Покажи задачи Жени в Jira",
            "What is Metronix architecture?",
            "Расскажи про аналитику данных",
            "Who is working on infrastructure?",
        ]
        for q in queries:
            assert not SessionManager._is_follow_up(q), f"Should NOT be follow-up: {q}"

    def test_empty_query(self) -> None:
        assert not SessionManager._is_follow_up("")
        assert not SessionManager._is_follow_up("   ")


class TestBuildCompositeQueryWithFollowUp:
    def setup_method(self) -> None:
        SessionManager.reset_instance()
        self.sm = SessionManager()

    def test_independent_query_skips_history(self) -> None:
        """Independent questions should NOT include history context."""
        self.sm.add_turn("u1", "ws1", "user", "Расскажи про архитектуру")
        self.sm.add_turn("u1", "ws1", "assistant", "Архитектура состоит из...")
        result = self.sm.build_composite_query("u1", "ws1", "What is the team doing this week?")
        # Independent query — no history included
        assert result == "What is the team doing this week?"
        assert "архитектуру" not in result

    def test_follow_up_includes_history(self) -> None:
        """Follow-up questions SHOULD include history context."""
        self.sm.add_turn("u1", "ws1", "user", "Tell me about team alpha")
        self.sm.add_turn("u1", "ws1", "assistant", "Team Alpha works on...")
        result = self.sm.build_composite_query("u1", "ws1", "What are their deadlines?")
        assert "team alpha" in result.lower()
        assert "their deadlines" in result.lower()

    def test_three_question_sequence(self) -> None:
        """Regression test: the exact scenario from the bug report.

        1. "Расскажи про архитектуру"  -> independent, no history
        2. "Какие задачи в Jira?"      -> independent, no history
        3. "What the team doing?"       -> independent, no history
        """
        # Q1
        r1 = self.sm.build_composite_query("u1", "ws1", "Расскажи про архитектуру")
        assert r1 == "Расскажи про архитектуру"
        self.sm.add_turn("u1", "ws1", "user", "Расскажи про архитектуру")
        self.sm.add_turn("u1", "ws1", "assistant", "...")

        # Q2
        r2 = self.sm.build_composite_query("u1", "ws1", "Какие задачи в Jira?")
        assert r2 == "Какие задачи в Jira?"
        assert "архитектуру" not in r2
        self.sm.add_turn("u1", "ws1", "user", "Какие задачи в Jira?")
        self.sm.add_turn("u1", "ws1", "assistant", "...")

        # Q3
        r3 = self.sm.build_composite_query("u1", "ws1", "What the team doing this week?")
        assert r3 == "What the team doing this week?"
        assert "архитектуру" not in r3
        assert "Jira" not in r3

    def test_follow_up_after_independent(self) -> None:
        """Follow-up after independent should include only recent history."""
        self.sm.add_turn("u1", "ws1", "user", "Tell me about team alpha")
        self.sm.add_turn("u1", "ws1", "assistant", "Team Alpha...")
        self.sm.add_turn("u1", "ws1", "user", "What are sprint goals?")
        self.sm.add_turn("u1", "ws1", "assistant", "Sprint goals are...")
        result = self.sm.build_composite_query("u1", "ws1", "And what about their deadlines?")
        assert "context:" in result
        assert "question:" in result
        assert "their deadlines" in result.lower()
