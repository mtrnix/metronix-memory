"""Unit tests for ``metatron.mcp.errors.handle_tool_error``.

MTRNIX-319: regression — a PG ``UntranslatableCharacterError`` whose message
contained the SQL text (with the string ``workspace_id`` in column names)
was misclassified as ``WORKSPACE_NOT_FOUND``. These tests pin the strict
exception-type-first mapping that fixes that."""

from __future__ import annotations

import pytest

from metatron.mcp.errors import ErrorCode, handle_tool_error


# Class names matter for ``handle_tool_error`` — it keys off ``type(exc).__name__``.
# These locally-defined classes are named after the real SQLAlchemy / asyncpg
# types so the mapper buckets them correctly.
class DBAPIError(Exception):  # noqa: N818 — match SQLAlchemy's real class name
    """Stand-in for a SQLAlchemy ``DBAPIError`` so the unit test stays
    dependency-free."""


class UntranslatableCharacterError(Exception):  # noqa: N818
    """Stand-in for the asyncpg-level encoding error."""


class WorkspaceNotFoundError(Exception):
    pass


class TestDBErrorMapping:
    def test_db_error_with_workspace_in_message_is_not_workspace_not_found(self) -> None:
        # Simulate the MTRNIX-319 incident: SQL INSERT with a Unicode
        # character landing on a SQL_ASCII-encoded cluster. The error
        # message contains the SQL text, which in turn contains the column
        # name ``workspace_id``. Before the fix this was bucketed as
        # WORKSPACE_NOT_FOUND with a misleading hint.
        exc = DBAPIError(
            "unsupported Unicode escape sequence\n"
            "DETAIL:  Unicode escape value could not be translated to the server's "
            "encoding SQL_ASCII.\n"
            "[SQL: INSERT INTO machine_events (id, workspace_id, event_type, ...)]"
        )
        err = handle_tool_error("metatron_memory_review_resolve", exc)

        assert err.code == ErrorCode.INTERNAL_ERROR
        # And specifically NOT the pre-fix false positive.
        assert err.code != ErrorCode.WORKSPACE_NOT_FOUND

    def test_untranslatable_character_error_maps_to_internal(self) -> None:
        exc = UntranslatableCharacterError("Unicode escape value could not be translated")
        err = handle_tool_error("tool_x", exc)
        assert err.code == ErrorCode.INTERNAL_ERROR


class TestWorkspaceErrorMapping:
    def test_workspace_typed_exception_still_maps_correctly(self) -> None:
        # A real workspace-typed exception still resolves to WORKSPACE_NOT_FOUND.
        exc = WorkspaceNotFoundError("Workspace 'abc' not found")
        err = handle_tool_error("tool_x", exc)
        assert err.code == ErrorCode.WORKSPACE_NOT_FOUND

    def test_workspace_in_message_on_untyped_error_still_maps(self) -> None:
        # Plain ``Exception`` whose message mentions workspace — message-based
        # fallback still applies (for non-DB exceptions).
        exc = Exception("workspace lookup failed")
        err = handle_tool_error("tool_x", exc)
        assert err.code == ErrorCode.WORKSPACE_NOT_FOUND


class TestOtherBuckets:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Qdrant connection refused", ErrorCode.QDRANT_UNAVAILABLE),
            ("Neo4j session expired", ErrorCode.GRAPH_UNAVAILABLE),
            ("Invalid cursor provided", ErrorCode.INVALID_CURSOR),
            ("Document not found", ErrorCode.DOCUMENT_NOT_FOUND),
            ("validation failed", ErrorCode.INVALID_PARAMS),
            ("unauthorized access", ErrorCode.AUTH_REQUIRED),
            ("HTTP 429 rate limited", ErrorCode.RATE_LIMITED),
        ],
    )
    def test_message_based_buckets_still_work(self, message: str, expected: ErrorCode) -> None:
        err = handle_tool_error("tool_x", Exception(message))
        assert err.code == expected

    def test_unknown_exception_maps_to_internal(self) -> None:
        err = handle_tool_error("tool_x", Exception("something weird happened"))
        assert err.code == ErrorCode.INTERNAL_ERROR
