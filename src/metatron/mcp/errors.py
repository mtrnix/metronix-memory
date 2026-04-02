"""Structured error system for MCP tools.

Provides consistent error format across all tools with code, message, hint,
and details fields for proper error handling and debugging.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Standard error codes for MCP tools."""

    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    QDRANT_UNAVAILABLE = "QDRANT_UNAVAILABLE"
    GRAPH_UNAVAILABLE = "GRAPH_UNAVAILABLE"
    INVALID_CURSOR = "INVALID_CURSOR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    INGESTION_FAILED = "INGESTION_FAILED"
    INVALID_PARAMS = "INVALID_PARAMS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"


class MCPError(BaseModel):
    """Structured error response for MCP tools.

    Attributes:
        code: Machine-readable error code
        message: Human-readable error message
        hint: Suggested action to resolve the error
        details: Additional context-specific data
    """

    code: ErrorCode
    message: str
    hint: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON-RPC response."""
        result = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.hint:
            result["hint"] = self.hint
        if self.details:
            result["details"] = self.details
        return result


# Error code to hint mapping for common errors
_ERROR_HINTS: dict[ErrorCode, str] = {
    ErrorCode.WORKSPACE_NOT_FOUND: "Check that the workspace_id is correct or create a new workspace",
    ErrorCode.QDRANT_UNAVAILABLE: "Ensure Qdrant vector database is running and accessible",
    ErrorCode.GRAPH_UNAVAILABLE: "Ensure Neo4j graph database is running and accessible",
    ErrorCode.INVALID_CURSOR: "Provide a valid cursor from a previous search response",
    ErrorCode.DOCUMENT_NOT_FOUND: "Verify the doc_label is correct or use search to find documents",
    ErrorCode.INGESTION_FAILED: "Check document format and try again, or contact administrator",
    ErrorCode.INVALID_PARAMS: "Review the tool parameters and provide valid values",
}


def handle_tool_error(
    tool_name: str,
    exception: Exception,
    details: dict[str, Any] | None = None,
) -> MCPError:
    """Convert an exception to a structured MCPError.

    Args:
        tool_name: Name of the tool where the error occurred
        exception: The original exception
        details: Additional context about the error

    Returns:
        Structured MCPError with appropriate code and hint
    """
    error_code = ErrorCode.INTERNAL_ERROR
    error_message = str(exception)

    # Map common exceptions to error codes
    exception_type = type(exception).__name__.upper()

    if "WORKSPACE" in exception_type or "workspace" in error_message.lower():
        error_code = ErrorCode.WORKSPACE_NOT_FOUND
    elif "QDRANT" in exception_type or "qdrant" in error_message.lower():
        error_code = ErrorCode.QDRANT_UNAVAILABLE
    elif (
        "NEO4J" in exception_type
        or "neo4j" in error_message.lower()
        or "graph" in error_message.lower()
    ):
        error_code = ErrorCode.GRAPH_UNAVAILABLE
    elif "CURSOR" in exception_type or "cursor" in error_message.lower():
        error_code = ErrorCode.INVALID_CURSOR
    elif "NOT FOUND" in exception_type or "not found" in error_message.lower():
        error_code = ErrorCode.DOCUMENT_NOT_FOUND
    elif "INVALID" in exception_type or "validation" in error_message.lower():
        error_code = ErrorCode.INVALID_PARAMS
    elif "AUTH" in exception_type or "unauthorized" in error_message.lower():
        error_code = ErrorCode.AUTH_REQUIRED
    elif "429" in error_message or "rate" in error_message.lower():
        error_code = ErrorCode.RATE_LIMITED

    # Get hint from mapping or generate default
    hint = _ERROR_HINTS.get(error_code)
    if not hint:
        hint = f"Error in {tool_name}. Check logs for details."

    # Build details dict
    error_details = {
        "tool": tool_name,
        "exception_type": exception_type,
    }
    if details:
        error_details.update(details)

    return MCPError(
        code=error_code,
        message=f"{tool_name}: {error_message}",
        hint=hint,
        details=error_details,
    )
