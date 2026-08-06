"""Tests for agent/sessions.py — SessionManager, ConversationTurn, composite query."""

from __future__ import annotations

from metronix.agent.sessions import ConversationTurn, SessionManager


class TestConversationTurn:
    def test_basic_fields(self) -> None:
        turn = ConversationTurn(role="user", content="hello")
        assert turn.role == "user"
        assert turn.content == "hello"
        assert turn.timestamp > 0

    def test_auto_timestamp(self) -> None:
        t1 = ConversationTurn(role="user", content="first")
        t2 = ConversationTurn(role="assistant", content="second")
        assert t2.timestamp >= t1.timestamp


class TestSessionManager:
    def setup_method(self) -> None:
        SessionManager.reset_instance()
        self.sm = SessionManager(max_history=5)

    def test_empty_history(self) -> None:
        history = self.sm.get_history("user1", "ws1")
        assert history == []

    def test_add_and_get(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "hello")
        self.sm.add_turn("u1", "ws1", "assistant", "hi there")
        history = self.sm.get_history("u1", "ws1")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "hello"}
        assert history[1] == {"role": "assistant", "content": "hi there"}

    def test_workspace_isolation(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "msg1")
        self.sm.add_turn("u1", "ws2", "user", "msg2")
        assert len(self.sm.get_history("u1", "ws1")) == 1
        assert len(self.sm.get_history("u1", "ws2")) == 1
        assert self.sm.get_history("u1", "ws1")[0]["content"] == "msg1"
        assert self.sm.get_history("u1", "ws2")[0]["content"] == "msg2"

    def test_user_isolation(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "msg1")
        self.sm.add_turn("u2", "ws1", "user", "msg2")
        assert len(self.sm.get_history("u1", "ws1")) == 1
        assert len(self.sm.get_history("u2", "ws1")) == 1

    def test_conversation_isolation_for_same_user_and_workspace(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "dm message", conversation_id="10")
        self.sm.add_turn("u1", "ws1", "user", "group message", conversation_id="20")

        assert self.sm.get_history("u1", "ws1", conversation_id="10") == [
            {"role": "user", "content": "dm message"}
        ]
        assert self.sm.get_history("u1", "ws1", conversation_id="20") == [
            {"role": "user", "content": "group message"}
        ]

    def test_clear_only_scoped_conversation(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "dm message", conversation_id="10")
        self.sm.add_turn("u1", "ws1", "user", "group message", conversation_id="20")

        self.sm.clear("u1", "ws1", conversation_id="10")

        assert self.sm.get_history("u1", "ws1", conversation_id="10") == []
        assert self.sm.get_history("u1", "ws1", conversation_id="20") == [
            {"role": "user", "content": "group message"}
        ]

    def test_max_history_trim(self) -> None:
        for i in range(10):
            self.sm.add_turn("u1", "ws1", "user", f"msg{i}")
        history = self.sm.get_history("u1", "ws1")
        assert len(history) == 5
        assert history[0]["content"] == "msg5"
        assert history[-1]["content"] == "msg9"

    def test_clear(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "hello")
        self.sm.add_turn("u1", "ws1", "assistant", "hi")
        self.sm.clear("u1", "ws1")
        assert self.sm.get_history("u1", "ws1") == []

    def test_clear_nonexistent(self) -> None:
        # Should not raise
        self.sm.clear("nonexistent", "ws1")

    def test_get_history_returns_copy(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "hello")
        h1 = self.sm.get_history("u1", "ws1")
        h2 = self.sm.get_history("u1", "ws1")
        assert h1 == h2
        h1.append({"role": "user", "content": "injected"})
        assert len(self.sm.get_history("u1", "ws1")) == 1


class TestCompositeQuery:
    def setup_method(self) -> None:
        SessionManager.reset_instance()
        self.sm = SessionManager()

    def test_no_history(self) -> None:
        result = self.sm.build_composite_query("u1", "ws1", "what is X?")
        assert result == "what is X?"

    def test_with_history(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "tell me about team alpha")
        self.sm.add_turn("u1", "ws1", "assistant", "Team Alpha works on...")
        result = self.sm.build_composite_query("u1", "ws1", "what are their deadlines?")
        assert "tell me about team alpha" in result
        assert "what are their deadlines?" in result
        assert "context:" in result
        assert "question:" in result

    def test_max_turns_limit(self) -> None:
        for i in range(10):
            self.sm.add_turn("u1", "ws1", "user", f"q{i}")
            self.sm.add_turn("u1", "ws1", "assistant", f"a{i}")
        result = self.sm.build_composite_query("u1", "ws1", "current", max_turns=2)
        assert "q8" in result
        assert "q9" in result
        assert "q0" not in result

    def test_only_user_messages_in_context(self) -> None:
        self.sm.add_turn("u1", "ws1", "user", "user_msg")
        self.sm.add_turn("u1", "ws1", "assistant", "assistant_msg")
        result = self.sm.build_composite_query("u1", "ws1", "follow-up")
        assert "user_msg" in result
        assert "assistant_msg" not in result


class TestSingleton:
    def setup_method(self) -> None:
        SessionManager.reset_instance()

    def test_get_instance_returns_same(self) -> None:
        sm1 = SessionManager.get_instance()
        sm2 = SessionManager.get_instance()
        assert sm1 is sm2

    def test_reset_instance(self) -> None:
        sm1 = SessionManager.get_instance()
        SessionManager.reset_instance()
        sm2 = SessionManager.get_instance()
        assert sm1 is not sm2

    def test_data_persists_in_singleton(self) -> None:
        sm = SessionManager.get_instance()
        sm.add_turn("u1", "ws1", "user", "hello")
        sm2 = SessionManager.get_instance()
        assert len(sm2.get_history("u1", "ws1")) == 1
