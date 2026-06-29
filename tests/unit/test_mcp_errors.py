"""Tests for metronix.mcp.errors — structured MCP error system."""

from __future__ import annotations

from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error


class TestMCPError:
    def test_to_dict_minimal(self) -> None:
        err = MCPError(code=ErrorCode.INTERNAL_ERROR, message="boom")
        d = err.to_dict()
        assert d == {"code": "INTERNAL_ERROR", "message": "boom"}

    def test_to_dict_with_hint_and_details(self) -> None:
        err = MCPError(
            code=ErrorCode.DOCUMENT_NOT_FOUND,
            message="not found",
            hint="try again",
            details={"tool": "get"},
        )
        d = err.to_dict()
        assert d["code"] == "DOCUMENT_NOT_FOUND"
        assert d["hint"] == "try again"
        assert d["details"]["tool"] == "get"


class TestHandleToolError:
    def test_generic_exception_maps_to_internal(self) -> None:
        err = handle_tool_error("test_tool", RuntimeError("oops"))
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert "test_tool" in err.message

    def test_workspace_keyword_maps_correctly(self) -> None:
        err = handle_tool_error("x", ValueError("workspace not available"))
        assert err.code == ErrorCode.WORKSPACE_NOT_FOUND

    def test_qdrant_keyword_maps_correctly(self) -> None:
        err = handle_tool_error("x", ConnectionError("qdrant unreachable"))
        assert err.code == ErrorCode.QDRANT_UNAVAILABLE

    def test_not_found_keyword_maps_correctly(self) -> None:
        err = handle_tool_error("x", ValueError("item not found"))
        assert err.code == ErrorCode.DOCUMENT_NOT_FOUND

    def test_auth_keyword_maps_correctly(self) -> None:
        err = handle_tool_error("x", PermissionError("unauthorized access"))
        assert err.code == ErrorCode.AUTH_REQUIRED

    def test_rate_limit_keyword_maps_correctly(self) -> None:
        err = handle_tool_error("x", RuntimeError("429 too many"))
        assert err.code == ErrorCode.RATE_LIMITED

    def test_details_are_merged(self) -> None:
        err = handle_tool_error("t", RuntimeError("x"), details={"k": "v"})
        assert err.details["k"] == "v"
        assert err.details["tool"] == "t"
