"""Unit tests for AsocVisibilityFilter — MCP transport (MTRNIX-370 Phase 2b).

Mock strategy: inject a pre-configured ``AsyncMock`` for ``AsocMcpClient`` via
the ``AsocVisibilityFilter.__init__`` constructor (set ``mcp_client=mock_client``).
This avoids patching module-level imports and keeps tests SDK-agnostic.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.integrations.asoc_mcp_client import (
    McpAuthError,
    McpProtocolError,
    McpUnavailableError,
    ToolNotAllowedError,
)
from metatron.integrations.asoc_visibility import (
    AsocVisibilityFilter,
    VisibilityFilterAuthError,
    VisibilityFilterConfigError,
    VisibilityFilterProtocolError,
    VisibilityFilterUnavailableError,
)

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_SESSION_ID = "asoc-session-abc123"


def _make_mcp_client(
    *,
    invoke_return: dict[str, Any] | None = None,
    invoke_side_effect: Any = None,
) -> AsyncMock:
    """Build a mock AsocMcpClient with a configurable invoke response.

    Default return: ``{"ids": []}`` (no visible IDs).
    """
    client = AsyncMock()
    if invoke_side_effect is not None:
        client.invoke.side_effect = invoke_side_effect
    else:
        content = invoke_return if invoke_return is not None else {"ids": []}
        _result = MagicMock()
        _result.content = [{"type": "json", "data": content}]
        client.invoke.return_value = _result
    return client


def _make_invoke_result(data: dict[str, Any]) -> MagicMock:
    """Build an AsocToolCallResult-like mock with JSON content block."""
    result = MagicMock()
    result.content = [{"type": "json", "data": data}]
    return result


def _make_filter(
    *,
    mcp_client: AsyncMock | None = None,
    timeout_seconds: float = 5.0,
    batch_size: int = 100,
    retry_attempts: int = 2,
) -> AsocVisibilityFilter:
    if mcp_client is None:
        mcp_client = _make_mcp_client()
    return AsocVisibilityFilter(
        mcp_client=mcp_client,
        timeout_seconds=timeout_seconds,
        batch_size=batch_size,
        retry_attempts=retry_attempts,
    )


def _make_asoc_chunk(
    chunk_id: str = "c1",
    entity_type: str = "issue",
    entity_id: str = "issue-1",
    parent_entity_id: str | None = None,
    source_type: str = "asoc",
) -> dict[str, Any]:
    """Build a MergedResult-shaped dict for an ASOC chunk."""
    metadata: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
    }
    if parent_entity_id is not None:
        metadata["parent_entity_id"] = parent_entity_id
    return {
        "chunk_id": chunk_id,
        "doc_label": f"asoc:{chunk_id}",
        "memory": {
            "source_type": source_type,
            "metadata": metadata,
        },
        "channels": ["dense"],
        "channel_scores": {"dense": 0.9},
    }


def _make_non_asoc_chunk(chunk_id: str = "nc1", source_type: str = "confluence") -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_label": f"{source_type}:{chunk_id}",
        "memory": {
            "source_type": source_type,
            "metadata": {"title": "some page"},
        },
        "channels": ["dense"],
        "channel_scores": {"dense": 0.8},
    }


# ---------------------------------------------------------------------------
# Test: empty / no-ASOC short-circuits
# ---------------------------------------------------------------------------


class TestShortCircuits:
    async def test_empty_input_returns_empty_no_mcp_call(self) -> None:
        client = _make_mcp_client()
        f = _make_filter(mcp_client=client)

        result, stats = await f.filter_chunks(_SESSION_ID, [])

        assert result == []
        assert stats.input_count == 0
        client.invoke.assert_not_called()

    async def test_all_non_asoc_chunks_pass_through_no_mcp_call(self) -> None:
        client = _make_mcp_client()
        f = _make_filter(mcp_client=client)

        chunks = [_make_non_asoc_chunk("n1"), _make_non_asoc_chunk("n2")]
        result, stats = await f.filter_chunks(_SESSION_ID, chunks)

        assert len(result) == 2
        assert stats.asoc_count == 0
        assert stats.pass_through_count == 2
        assert stats.batches_issued == 0
        client.invoke.assert_not_called()

    async def test_no_mcp_client_no_asoc_chunks_passes_through(self) -> None:
        f = AsocVisibilityFilter(mcp_client=None)
        chunks = [_make_non_asoc_chunk("n1")]
        result, stats = await f.filter_chunks(_SESSION_ID, chunks)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Test: auth guard
# ---------------------------------------------------------------------------


class TestAuthGuard:
    async def test_empty_session_id_raises_auth_error(self) -> None:
        f = _make_filter()
        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks("", [_make_asoc_chunk()])

    async def test_blank_session_id_raises_auth_error(self) -> None:
        f = _make_filter()
        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks("   ", [_make_asoc_chunk()])


# ---------------------------------------------------------------------------
# Test: config error (no MCP client)
# ---------------------------------------------------------------------------


class TestConfigError:
    async def test_none_mcp_client_with_asoc_chunks_raises_config_error(self) -> None:
        f = AsocVisibilityFilter(mcp_client=None)
        chunks = [_make_asoc_chunk("c1", entity_type="issue", entity_id="issue-1")]
        with pytest.raises(VisibilityFilterConfigError):
            await f.filter_chunks(_SESSION_ID, chunks)

    async def test_tool_not_allowed_raises_config_error(self) -> None:
        client = _make_mcp_client(invoke_side_effect=ToolNotAllowedError("not in whitelist"))
        f = _make_filter(mcp_client=client, retry_attempts=0)
        chunks = [_make_asoc_chunk()]
        with pytest.raises(VisibilityFilterConfigError, match="whitelist"):
            await f.filter_chunks(_SESSION_ID, chunks)


# ---------------------------------------------------------------------------
# Test: entity → resource_type mapping (regression from Phase 1)
# ---------------------------------------------------------------------------


class TestEntityMapping:
    async def _filter_single(
        self, entity_type: str, entity_id: str, *, visible: bool
    ) -> list[Any]:
        is_child = entity_type in {
            "comment",
            "issue_history",
            "sbom",
            "dependency",
            "quality_gate",
            "gate",
            "event",
        }
        if is_child:
            chunk = _make_asoc_chunk(
                entity_type=entity_type,
                entity_id="child-1",
                parent_entity_id=entity_id,
            )
        else:
            chunk = _make_asoc_chunk(
                entity_type=entity_type,
                entity_id=entity_id,
            )

        visible_ids = [entity_id] if visible else []
        client = _make_mcp_client(invoke_return={"ids": visible_ids})
        f = _make_filter(mcp_client=client)

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        return result

    async def test_root_entity_uses_own_id(self) -> None:
        """issue entity_id is used as the auth key directly."""
        client = _make_mcp_client(invoke_return={"ids": ["issue-42"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(entity_type="issue", entity_id="issue-42")

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        # Verify the correct resource_type and id were sent to MCP invoke
        call_kwargs = client.invoke.call_args
        assert call_kwargs.kwargs["tool_name"] == "asoc_visibility_filter"
        args = call_kwargs.kwargs["arguments"]
        assert args["resource_type"] == "issue"
        assert "issue-42" in args["ids"]

    async def test_child_entity_uses_parent_id(self) -> None:
        """comment uses parent_entity_id (the issue id) as the auth key."""
        client = _make_mcp_client(invoke_return={"ids": ["issue-99"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(
            entity_type="comment",
            entity_id="comment-1",
            parent_entity_id="issue-99",
        )

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        args = client.invoke.call_args.kwargs["arguments"]
        assert args["resource_type"] == "issue"
        assert "issue-99" in args["ids"]

    async def test_quality_gate_maps_to_gate_resource(self) -> None:
        """quality_gate entity_type (legacy alias) must map to resource_type 'gate'."""
        client = _make_mcp_client(invoke_return={"ids": ["gate-1"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(
            entity_type="quality_gate",
            entity_id="child-1",
            parent_entity_id="gate-1",
        )

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        args = client.invoke.call_args.kwargs["arguments"]
        assert args["resource_type"] == "gate"
        assert args["resource_type"] != "project"

    async def test_gate_maps_to_gate_resource(self) -> None:
        """gate entity_type maps to resource_type 'gate' (ASOC §1.1)."""
        client = _make_mcp_client(invoke_return={"ids": ["gate-1"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(
            entity_type="gate",
            entity_id="child-1",
            parent_entity_id="gate-1",
        )

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        args = client.invoke.call_args.kwargs["arguments"]
        assert args["resource_type"] == "gate"

    async def test_sbom_maps_to_layer_resource(self) -> None:
        result = await self._filter_single("sbom", "layer-1", visible=True)
        assert len(result) == 1

    async def test_scan_result_maps_to_scan_resource(self) -> None:
        """scan_result entity_type must map to resource_type 'scan' (ASOC contract §1.1)."""
        client = _make_mcp_client(invoke_return={"ids": ["scan-1"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(entity_type="scan_result", entity_id="scan-1")

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        args = client.invoke.call_args.kwargs["arguments"]
        # ASOC §1.1: resource_type must be "scan", NOT "scan_result"
        assert args["resource_type"] == "scan"
        assert args["resource_type"] != "scan_result"

    async def test_unknown_entity_type_is_dropped(self) -> None:
        client = _make_mcp_client(invoke_return={"ids": ["x-1"]})
        f = _make_filter(mcp_client=client)
        # Unknown entity type → _resolve_parent_id returns None → dropped
        chunk = _make_asoc_chunk(entity_type="unknown_type", entity_id="x-1")

        result, stats = await f.filter_chunks(_SESSION_ID, [chunk])
        # The unknown chunk is in "dropped_malformed" and never sent to MCP.
        assert len(result) == 0

    async def test_missing_parent_id_for_child_is_dropped(self) -> None:
        client = _make_mcp_client(invoke_return={"ids": ["issue-1"]})
        f = _make_filter(mcp_client=client)
        # comment without parent_entity_id → dropped
        chunk = _make_asoc_chunk(
            entity_type="comment",
            entity_id="c-1",
            parent_entity_id=None,
        )
        chunk["memory"]["metadata"].pop("parent_entity_id", None)

        result, stats = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 0

    async def test_sbom_with_parent_groups_under_layer_resource(self) -> None:
        """sbom is a child entity — it must group under resource_type 'layer' via parent_id.

        Regression guard: sbom must NOT be sent as a standalone 'sbom' resource_type
        (ASOC §1.1 — sbom is not a valid resource_type; sbom chunks use parent_entity_id
        pointing at the parent layer).
        """
        client = _make_mcp_client(invoke_return={"ids": ["layer-99"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(
            entity_type="sbom",
            entity_id="sbom-1",
            parent_entity_id="layer-99",
        )

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        args = client.invoke.call_args.kwargs["arguments"]
        # Must be "layer", never "sbom"
        assert args["resource_type"] == "layer"
        assert args["resource_type"] != "sbom"
        assert "layer-99" in args["ids"]

    async def test_sbom_without_parent_id_is_dropped(self) -> None:
        """sbom chunk without parent_entity_id must be dropped (fail-closed).

        sbom is a child entity — if parent_entity_id is absent, there is no
        auth key to look up, so the chunk is silently dropped.
        """
        client = _make_mcp_client(invoke_return={"ids": ["sbom-orphan"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk(
            entity_type="sbom",
            entity_id="sbom-orphan",
            parent_entity_id=None,
        )
        chunk["memory"]["metadata"].pop("parent_entity_id", None)

        result, stats = await f.filter_chunks(_SESSION_ID, [chunk])
        # Dropped malformed (no parent_entity_id) — never sent to ASOC
        assert len(result) == 0
        client.invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Test: grouping, batching, parallel
# ---------------------------------------------------------------------------


class TestGroupingAndBatching:
    async def test_grouping_multiple_resource_types(self) -> None:
        """Chunks of different resource_types lead to separate MCP invoke calls."""
        invoke_results: list[MagicMock] = []
        for rt in ("issue", "project", "layer"):
            r = MagicMock()
            r.content = [{"type": "json", "data": {"ids": [f"{rt}-1"]}}]
            invoke_results.append(r)

        client = AsyncMock()
        client.invoke.side_effect = invoke_results
        f = _make_filter(mcp_client=client)

        chunks = [
            _make_asoc_chunk("c1", "issue", "issue-1"),
            _make_asoc_chunk("c2", "project", "project-1"),
            _make_asoc_chunk("c3", "layer", "layer-1"),
        ]

        result, stats = await f.filter_chunks(_SESSION_ID, chunks)
        # 3 invoke calls: one per resource_type
        assert client.invoke.call_count == 3
        assert len(result) == 3

    async def test_batching_above_batch_size(self) -> None:
        """101 IDs with batch_size=100 → 2 MCP invoke calls for that resource type."""

        def _side_effect(*, session_id: str, tool_name: str, arguments: dict) -> MagicMock:
            r = MagicMock()
            r.content = [{"type": "json", "data": {"ids": arguments["ids"]}}]
            return r

        client = AsyncMock()
        client.invoke.side_effect = _side_effect
        f = _make_filter(mcp_client=client, batch_size=100)
        chunks = [_make_asoc_chunk(f"c{i}", "issue", f"issue-{i}") for i in range(101)]

        result, stats = await f.filter_chunks(_SESSION_ID, chunks)
        assert client.invoke.call_count == 2
        assert stats.batches_issued == 2
        assert len(result) == 101

    async def test_parallel_across_resource_types(self) -> None:
        """asyncio.gather is used across resource types — verify all calls complete."""
        called_resource_types: list[str] = []

        async def _side_effect(*, session_id: str, tool_name: str, arguments: dict) -> MagicMock:
            called_resource_types.append(arguments["resource_type"])
            r = MagicMock()
            r.content = [{"type": "json", "data": {"ids": arguments["ids"]}}]
            return r

        client = AsyncMock()
        client.invoke.side_effect = _side_effect
        f = _make_filter(mcp_client=client)

        chunks = [
            _make_asoc_chunk("c1", "issue", "issue-1"),
            _make_asoc_chunk("c2", "project", "proj-1"),
        ]
        result, _ = await f.filter_chunks(_SESSION_ID, chunks)
        assert set(called_resource_types) == {"issue", "project"}
        assert len(result) == 2

    async def test_visible_ids_merge_across_batches(self) -> None:
        """Two batches for the same resource_type merge their visible_ids."""
        results_queue: list[MagicMock] = [
            _make_invoke_result({"ids": ["issue-0", "issue-1"]}),
            _make_invoke_result({"ids": ["issue-2", "issue-3"]}),
        ]

        client = AsyncMock()
        client.invoke.side_effect = results_queue
        f = _make_filter(mcp_client=client, batch_size=2)
        chunks = [_make_asoc_chunk(f"c{i}", "issue", f"issue-{i}") for i in range(4)]

        result, _ = await f.filter_chunks(_SESSION_ID, chunks)
        assert len(result) == 4

    async def test_output_preserves_original_order(self) -> None:
        """The output list must be in the same order as the input."""
        client = _make_mcp_client(invoke_return={"ids": ["issue-1", "issue-2"]})
        f = _make_filter(mcp_client=client)
        chunks = [
            _make_non_asoc_chunk("n1"),
            _make_asoc_chunk("a1", "issue", "issue-1"),
            _make_non_asoc_chunk("n2"),
            _make_asoc_chunk("a2", "issue", "issue-2"),
        ]

        result, _ = await f.filter_chunks(_SESSION_ID, chunks)
        ids = [r["chunk_id"] for r in result]
        assert ids == ["n1", "a1", "n2", "a2"]

    async def test_chunks_not_in_visible_ids_are_dropped(self) -> None:
        client = _make_mcp_client(invoke_return={"ids": ["issue-allowed"]})
        f = _make_filter(mcp_client=client)
        chunks = [
            _make_asoc_chunk("keep", "issue", "issue-allowed"),
            _make_asoc_chunk("drop", "issue", "issue-denied"),
        ]

        result, stats = await f.filter_chunks(_SESSION_ID, chunks)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "keep"
        assert stats.dropped_count == 1

    async def test_one_resource_type_returns_empty_ids_others_unaffected(self) -> None:
        """One resource_type returns empty ids; chunks from other types still pass."""

        async def _side_effect(*, session_id: str, tool_name: str, arguments: dict) -> MagicMock:
            rt = arguments["resource_type"]
            ids = arguments["ids"] if rt != "project" else []
            r = MagicMock()
            r.content = [{"type": "json", "data": {"ids": ids}}]
            return r

        client = AsyncMock()
        client.invoke.side_effect = _side_effect
        f = _make_filter(mcp_client=client)

        chunks = [
            _make_asoc_chunk("i1", "issue", "issue-1"),
            _make_asoc_chunk("p1", "project", "proj-1"),
        ]
        result, stats = await f.filter_chunks(_SESSION_ID, chunks)
        # project chunk dropped; issue chunk kept
        assert len(result) == 1
        assert result[0]["chunk_id"] == "i1"


# ---------------------------------------------------------------------------
# Test: MCP error handling
# ---------------------------------------------------------------------------


class TestMcpErrors:
    async def test_mcp_auth_error_raises_filter_auth_error_no_retry(self) -> None:
        client = _make_mcp_client(invoke_side_effect=McpAuthError("session invalid"))
        f = _make_filter(mcp_client=client, retry_attempts=2)
        chunk = _make_asoc_chunk()

        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks(_SESSION_ID, [chunk])
        # McpAuthError → no retry (called exactly once)
        assert client.invoke.call_count == 1

    async def test_mcp_unavailable_retries_then_raises(self) -> None:
        """retry_attempts=2 → 3 total calls for McpUnavailableError."""
        client = _make_mcp_client(invoke_side_effect=McpUnavailableError("server down"))
        f = _make_filter(mcp_client=client, retry_attempts=2)
        chunk = _make_asoc_chunk()

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(VisibilityFilterUnavailableError),
        ):
            await f.filter_chunks(_SESSION_ID, [chunk])

        assert client.invoke.call_count == 3

    async def test_mcp_protocol_error_retries_then_raises(self) -> None:
        """McpProtocolError is transient — retried up to retry_attempts."""
        client = _make_mcp_client(invoke_side_effect=McpProtocolError("malformed envelope"))
        f = _make_filter(mcp_client=client, retry_attempts=2)
        chunk = _make_asoc_chunk()

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(VisibilityFilterProtocolError),
        ):
            await f.filter_chunks(_SESSION_ID, [chunk])

        assert client.invoke.call_count == 3

    async def test_mcp_unavailable_then_success_on_retry(self) -> None:
        """McpUnavailableError on first attempt, success on retry."""
        ok_result = _make_invoke_result({"ids": ["issue-1"]})

        client = AsyncMock()
        client.invoke.side_effect = [
            McpUnavailableError("first attempt failed"),
            ok_result,
        ]
        f = _make_filter(mcp_client=client, retry_attempts=2)
        chunk = _make_asoc_chunk("c1", "issue", "issue-1")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result, _ = await f.filter_chunks(_SESSION_ID, [chunk])

        assert len(result) == 1
        assert client.invoke.call_count == 2

    async def test_mcp_protocol_error_then_success_on_retry(self) -> None:
        """McpProtocolError on first attempt, success on retry."""
        ok_result = _make_invoke_result({"ids": ["issue-1"]})

        client = AsyncMock()
        client.invoke.side_effect = [
            McpProtocolError("bad envelope"),
            ok_result,
        ]
        f = _make_filter(mcp_client=client, retry_attempts=2)
        chunk = _make_asoc_chunk("c1", "issue", "issue-1")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result, _ = await f.filter_chunks(_SESSION_ID, [chunk])

        assert len(result) == 1
        assert client.invoke.call_count == 2

    async def test_tool_not_allowed_raises_config_error_no_retry(self) -> None:
        """ToolNotAllowedError is a config bug — should fail immediately."""
        client = _make_mcp_client(invoke_side_effect=ToolNotAllowedError("asoc_visibility_filter"))
        f = _make_filter(mcp_client=client, retry_attempts=2)
        chunk = _make_asoc_chunk()

        with pytest.raises(VisibilityFilterConfigError):
            await f.filter_chunks(_SESSION_ID, [chunk])

        # Not retried
        assert client.invoke.call_count == 1

    async def test_malformed_response_missing_ids_raises_protocol_error(self) -> None:
        """Response missing 'ids' field → VisibilityFilterProtocolError."""
        result = _make_invoke_result({"something_else": []})
        client = _make_mcp_client()
        client.invoke.return_value = result
        f = _make_filter(mcp_client=client, retry_attempts=0)
        chunk = _make_asoc_chunk()

        with pytest.raises(VisibilityFilterProtocolError):
            await f.filter_chunks(_SESSION_ID, [chunk])

    async def test_malformed_response_ids_not_a_list_raises_protocol_error(self) -> None:
        """Response where 'ids' is not a list → VisibilityFilterProtocolError."""
        result = _make_invoke_result({"ids": "not-a-list"})
        client = _make_mcp_client()
        client.invoke.return_value = result
        f = _make_filter(mcp_client=client, retry_attempts=0)
        chunk = _make_asoc_chunk()

        with pytest.raises(VisibilityFilterProtocolError):
            await f.filter_chunks(_SESSION_ID, [chunk])

    async def test_text_content_block_parsed(self) -> None:
        """MCP content block with type='text' and JSON string also works."""
        import json

        result = MagicMock()
        result.content = [{"type": "text", "text": json.dumps({"ids": ["issue-1"]})}]
        client = AsyncMock()
        client.invoke.return_value = result
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk("c1", "issue", "issue-1")

        output, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(output) == 1


# ---------------------------------------------------------------------------
# Test: overall budget timeout
# ---------------------------------------------------------------------------


class TestBudgetTimeout:
    async def test_overall_budget_timeout_raises_unavailable(self) -> None:
        """Slow mock + very low budget → TimeoutError → VisibilityFilterUnavailableError."""

        async def _slow_invoke(**kwargs: Any) -> MagicMock:
            await asyncio.sleep(10)  # longer than budget
            return _make_invoke_result({"ids": []})

        client = AsyncMock()
        client.invoke.side_effect = _slow_invoke
        f = _make_filter(mcp_client=client, timeout_seconds=0.01)
        chunk = _make_asoc_chunk()

        with pytest.raises(VisibilityFilterUnavailableError, match="budget exceeded"):
            await f.filter_chunks(_SESSION_ID, [chunk])


# ---------------------------------------------------------------------------
# Test: health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_health_check_returns_false_when_no_client(self) -> None:
        f = AsocVisibilityFilter(mcp_client=None)
        result = await f.health_check()
        assert result is False

    async def test_health_check_returns_true_when_client_present(self) -> None:
        client = _make_mcp_client()
        f = _make_filter(mcp_client=client)
        result = await f.health_check()
        assert result is True


# ---------------------------------------------------------------------------
# Test: stats object
# ---------------------------------------------------------------------------


class TestStats:
    async def test_stats_object_populated_correctly(self) -> None:
        client = _make_mcp_client(invoke_return={"ids": ["issue-1"]})
        f = _make_filter(mcp_client=client, batch_size=100)
        chunks = [
            _make_non_asoc_chunk("n1"),
            _make_asoc_chunk("a1", "issue", "issue-1"),
            _make_asoc_chunk("a2", "issue", "issue-2"),
        ]

        result, stats = await f.filter_chunks(_SESSION_ID, chunks)

        assert stats.input_count == 3
        assert stats.asoc_count == 2
        assert stats.pass_through_count == 1
        assert stats.output_count == 2  # 1 pass-through + 1 allowed ASOC
        assert stats.dropped_count == 1
        assert stats.batches_issued == 1
        assert stats.elapsed_ms >= 0
        assert "issue" in stats.resource_type_counts
        assert stats.resource_type_counts["issue"] == 2

    async def test_stats_no_asoc_chunks(self) -> None:
        client = _make_mcp_client()
        f = _make_filter(mcp_client=client)

        chunks = [_make_non_asoc_chunk("n1"), _make_non_asoc_chunk("n2")]
        result, stats = await f.filter_chunks(_SESSION_ID, chunks)

        assert stats.asoc_count == 0
        assert stats.batches_issued == 0
        assert stats.pass_through_count == 2
        assert stats.dropped_count == 0
        client.invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Test: from_settings (new signature requires mcp_client argument)
# ---------------------------------------------------------------------------


class TestFromSettings:
    def test_from_settings_constructs_correctly(self) -> None:
        from metatron.core.config import Settings

        settings = Settings(
            METATRON_ASOC_VISIBILITY_FILTER_TIMEOUT_SECONDS="7.0",
            METATRON_ASOC_VISIBILITY_FILTER_BATCH_SIZE="50",
            METATRON_ASOC_VISIBILITY_FILTER_RETRY_ATTEMPTS="1",
        )
        client = _make_mcp_client()
        f = AsocVisibilityFilter.from_settings(settings, mcp_client=client)
        assert f.timeout_seconds == 7.0
        assert f.batch_size == 50
        assert f.retry_attempts == 1

    def test_from_settings_none_client_disables_filter(self) -> None:
        from metatron.core.config import Settings

        settings = Settings()
        f = AsocVisibilityFilter.from_settings(settings, mcp_client=None)
        assert f._mcp_client is None


# ---------------------------------------------------------------------------
# Test: Qdrant payload layout variant (nested under 'payload')
# ---------------------------------------------------------------------------


class TestMetadataExtraction:
    async def test_nested_payload_metadata_extracted(self) -> None:
        """Older Qdrant payloads nest metadata under memory.payload.metadata."""
        client = _make_mcp_client(invoke_return={"ids": ["issue-1"]})
        f = _make_filter(mcp_client=client)
        chunk: dict[str, Any] = {
            "chunk_id": "c1",
            "doc_label": "asoc:c1",
            "memory": {
                "source_type": "asoc",
                "payload": {
                    "source_type": "asoc",
                    "metadata": {
                        "entity_type": "issue",
                        "entity_id": "issue-1",
                    },
                },
            },
            "channels": ["dense"],
            "channel_scores": {},
        }

        result, _ = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1

    async def test_source_type_from_nested_payload(self) -> None:
        """source_type resolved from memory.payload.source_type when not in memory."""
        client = _make_mcp_client()
        f = _make_filter(mcp_client=client)
        chunk: dict[str, Any] = {
            "chunk_id": "nc1",
            "doc_label": "confluence:nc1",
            "memory": {
                "payload": {
                    "source_type": "confluence",
                    "metadata": {"title": "page"},
                },
            },
            "channels": ["dense"],
            "channel_scores": {},
        }

        result, stats = await f.filter_chunks(_SESSION_ID, [chunk])
        assert len(result) == 1
        assert stats.pass_through_count == 1
        client.invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Test: MCP call arguments (session_id forwarding)
# ---------------------------------------------------------------------------


class TestMcpCallArguments:
    async def test_session_id_forwarded_to_invoke(self) -> None:
        """The session_id must be forwarded as the first argument to mcp_client.invoke."""
        client = _make_mcp_client(invoke_return={"ids": ["issue-1"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk("c1", "issue", "issue-1")

        await f.filter_chunks("my-session-123", [chunk])

        call_kwargs = client.invoke.call_args.kwargs
        assert call_kwargs["session_id"] == "my-session-123"
        assert call_kwargs["tool_name"] == "asoc_visibility_filter"

    async def test_invoke_arguments_match_contract(self) -> None:
        """Arguments must match ASOC_API_CONTRACT.md §3.2 shape."""
        client = _make_mcp_client(invoke_return={"ids": ["issue-1"]})
        f = _make_filter(mcp_client=client)
        chunk = _make_asoc_chunk("c1", "issue", "issue-1")

        await f.filter_chunks(_SESSION_ID, [chunk])

        args = client.invoke.call_args.kwargs["arguments"]
        assert "resource_type" in args
        assert "ids" in args
        assert isinstance(args["ids"], list)
