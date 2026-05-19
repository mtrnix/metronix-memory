"""Unit tests for ASOC SSE helper functions (MTRNIX-354, T4)."""

from __future__ import annotations

import json

from metatron.chat.asoc_sse import (
    sse_chunk,
    sse_done,
    sse_error,
    sse_sources,
    sse_status,
    sse_tool_call,
)


class TestSseStatus:
    def test_event_type(self) -> None:
        result = sse_status("processing")
        assert result["event"] == "status"

    def test_data_contains_status(self) -> None:
        result = sse_status("retrieving")
        data = json.loads(result["data"])
        assert data["status"] == "retrieving"

    def test_returns_dict_with_event_and_data_keys(self) -> None:
        result = sse_status("x")
        assert set(result.keys()) == {"event", "data"}


class TestSseChunk:
    def test_event_type(self) -> None:
        result = sse_chunk("hello")
        assert result["event"] == "chunk"

    def test_data_contains_text(self) -> None:
        result = sse_chunk("hello world")
        data = json.loads(result["data"])
        assert data["text"] == "hello world"

    def test_empty_string(self) -> None:
        result = sse_chunk("")
        data = json.loads(result["data"])
        assert data["text"] == ""


class TestSseSources:
    def test_event_type(self) -> None:
        result = sse_sources([])
        assert result["event"] == "sources"

    def test_data_contains_sources(self) -> None:
        citations = [{"anchor": "[1]", "title": "Doc"}]
        result = sse_sources(citations)
        data = json.loads(result["data"])
        assert data["sources"] == citations

    def test_empty_sources(self) -> None:
        result = sse_sources([])
        data = json.loads(result["data"])
        assert data["sources"] == []


class TestSseToolCall:
    def test_event_type(self) -> None:
        result = sse_tool_call("asoc_list_issues", "running")
        assert result["event"] == "tool_call"

    def test_data_contains_tool_and_status(self) -> None:
        result = sse_tool_call("my_tool", "done")
        data = json.loads(result["data"])
        assert data["tool"] == "my_tool"
        assert data["status"] == "done"

    def test_reason_included_when_provided(self) -> None:
        result = sse_tool_call("my_tool", "error", reason="not_allowed")
        data = json.loads(result["data"])
        assert data["reason"] == "not_allowed"

    def test_reason_omitted_when_not_provided(self) -> None:
        result = sse_tool_call("my_tool", "running")
        data = json.loads(result["data"])
        assert "reason" not in data


class TestSseDone:
    def test_event_type(self) -> None:
        result = sse_done("ws-1", "thread-1")
        assert result["event"] == "done"

    def test_data_contains_workspace_and_thread(self) -> None:
        result = sse_done("ws-abc", "tid-123")
        data = json.loads(result["data"])
        assert data["workspace_id"] == "ws-abc"
        assert data["thread_id"] == "tid-123"

    def test_none_thread_id_serialized(self) -> None:
        result = sse_done("ws-abc", None)
        data = json.loads(result["data"])
        assert data["thread_id"] is None


class TestSseError:
    def test_event_type(self) -> None:
        result = sse_error("rate_limited", "Too many requests")
        assert result["event"] == "error"

    def test_data_contains_code_and_message(self) -> None:
        result = sse_error("timeout", "Request timed out")
        data = json.loads(result["data"])
        assert data["code"] == "timeout"
        assert data["message"] == "Request timed out"
