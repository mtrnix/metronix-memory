"""Unit tests for ASOC chat prompt assembly helpers (MTRNIX-354, T4).

Tests: build_system_prompt, assemble_history, assemble_context.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from metatron.chat.asoc_prompt import assemble_context, assemble_history, build_system_prompt

# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_includes_project_name(self) -> None:
        result = build_system_prompt("MyProject", [])
        assert "MyProject" in result

    def test_no_tools_shows_no_live_tools(self) -> None:
        result = build_system_prompt("P", [])
        assert "(no live tools available)" in result

    def test_tools_listed_in_prompt(self) -> None:
        tool = MagicMock()
        tool.name = "asoc_list_issues"
        tool.description = "List issues in a project"

        result = build_system_prompt("P", [tool])
        assert "asoc_list_issues" in result
        assert "List issues in a project" in result

    def test_multiple_tools_all_listed(self) -> None:
        tools = []
        for i in range(3):
            t = MagicMock()
            t.name = f"asoc_tool_{i}"
            t.description = f"desc_{i}"
            tools.append(t)

        result = build_system_prompt("P", tools)
        for i in range(3):
            assert f"asoc_tool_{i}" in result

    def test_hard_rules_present(self) -> None:
        result = build_system_prompt("P", [])
        # At least some of the hard rules should be mentioned
        assert "HARD RULES" in result
        assert "fabricate" in result.lower() or "never fabricate" in result.lower()


# ---------------------------------------------------------------------------
# assemble_history
# ---------------------------------------------------------------------------


def _make_db_message(role: str, content: str) -> Any:
    msg = MagicMock()
    msg.role = role
    msg.content = content
    return msg


class TestAssembleHistory:
    def test_empty_inputs_returns_empty(self) -> None:
        result = assemble_history([], None, max_turns=10, max_tokens=4096)
        assert result == []

    def test_db_messages_converted(self) -> None:
        msgs = [
            _make_db_message("user", "hello"),
            _make_db_message("assistant", "hi"),
        ]
        result = assemble_history(msgs, None, max_turns=10, max_tokens=4096)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "hello"}
        assert result[1] == {"role": "assistant", "content": "hi"}

    def test_body_history_appended_when_db_empty(self) -> None:
        body_hist = [{"role": "user", "content": "from body"}]
        result = assemble_history([], body_hist, max_turns=10, max_tokens=4096)
        assert len(result) == 1
        assert result[0]["content"] == "from body"

    def test_max_turns_cap_applied(self) -> None:
        # 6 db messages, max_turns=2 → keep last 4 messages
        msgs = [_make_db_message("user", f"msg {i}") for i in range(6)]
        result = assemble_history(msgs, None, max_turns=2, max_tokens=99999)
        assert len(result) == 4
        assert result[0]["content"] == "msg 2"

    def test_token_budget_drops_oldest_first(self) -> None:
        # 3 messages with big content; budget forces dropping oldest
        msgs = [
            _make_db_message("user", "a " * 500),   # ~375 tokens
            _make_db_message("assistant", "b " * 500),
            _make_db_message("user", "c"),
        ]
        # Very tight budget — only last message should fit
        result = assemble_history(msgs, None, max_turns=10, max_tokens=10)
        # Should have dropped early messages
        assert len(result) < 3

    def test_body_history_invalid_entries_skipped(self) -> None:
        body_hist = [
            {"role": "", "content": "empty role"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "valid"},
        ]
        result = assemble_history([], body_hist, max_turns=10, max_tokens=4096)
        # Only the valid entry should be included
        assert len(result) == 1
        assert result[0]["content"] == "valid"

    def test_oldest_first_ordering_preserved(self) -> None:
        msgs = [
            _make_db_message("user", "first"),
            _make_db_message("assistant", "second"),
            _make_db_message("user", "third"),
        ]
        result = assemble_history(msgs, None, max_turns=10, max_tokens=4096)
        assert result[0]["content"] == "first"
        assert result[2]["content"] == "third"


# ---------------------------------------------------------------------------
# assemble_context
# ---------------------------------------------------------------------------


def _make_mr(title: str = "Doc", source_type: str = "issue", content: str = "body") -> dict:
    return {
        "memory": {
            "title": title,
            "source_type": source_type,
            "entity_id": "e-123",
            "content": content,
        }
    }


class TestAssembleContext:
    def test_empty_results_returns_empty_string(self) -> None:
        result = assemble_context([], max_chars=1000)
        assert result == ""

    def test_single_result_formatted(self) -> None:
        result = assemble_context([_make_mr("MyDoc", "issue", "some content")], max_chars=5000)
        assert "MyDoc" in result
        assert "some content" in result
        assert "[1]" in result

    def test_numbered_sequentially(self) -> None:
        mrs = [_make_mr(f"Doc{i}", "issue", "body") for i in range(3)]
        result = assemble_context(mrs, max_chars=10000)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result

    def test_max_chars_truncates_whole_chunks(self) -> None:
        big_content = "x" * 1000
        mrs = [_make_mr(f"Doc{i}", "issue", big_content) for i in range(10)]
        result = assemble_context(mrs, max_chars=3000)
        # Should not exceed the cap (with at most a little slack for section headers)
        assert len(result) <= 3200  # allow small header overhead

    def test_content_truncated_at_max_chars_per_chunk(self) -> None:
        very_long = "y" * 5000
        result = assemble_context([_make_mr(content=very_long)], max_chars=100000)
        # Content in result should not contain the full 5000 chars
        assert "y" * 5000 not in result
        assert "y" * 2000 in result  # _MAX_CHARS_PER_CHUNK = 2000

    def test_missing_fields_fall_back_gracefully(self) -> None:
        mr = {"memory": {}}  # all optional fields missing
        result = assemble_context([mr], max_chars=5000)
        # Should still produce some output (Untitled)
        assert "Untitled" in result

    def test_payload_fallback_for_nested_struct(self) -> None:
        mr = {
            "memory": {
                "payload": {
                    "title": "Nested",
                    "source_type": "layer",
                    "content": "nested content",
                }
            }
        }
        result = assemble_context([mr], max_chars=5000)
        assert "Nested" in result
        assert "nested content" in result
