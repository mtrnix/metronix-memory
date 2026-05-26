"""Unit tests for AsocVisibilityFilter.

Mock strategy: inject a pre-configured ``httpx.AsyncClient`` mock via the
``AsocVisibilityFilter.__init__`` (set ``filter._client = mock_client``).
This avoids patching module-level imports and keeps tests SDK-agnostic.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

_BASE_URL = "https://asoc.example.com"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEifQ.sig"


def _make_filter(
    *,
    base_url: str = _BASE_URL,
    timeout_seconds: float = 5.0,
    batch_size: int = 100,
    retry_attempts: int = 2,
) -> AsocVisibilityFilter:
    f = AsocVisibilityFilter(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        batch_size=batch_size,
        retry_attempts=retry_attempts,
    )
    return f


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


def _mock_response(status_code: int = 200, json_data: Any = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _inject_mock_client(f: AsocVisibilityFilter, mock_client: MagicMock) -> None:
    """Replace the internal httpx client with a mock."""
    f._client = mock_client


# ---------------------------------------------------------------------------
# Test: empty / no-ASOC short-circuits
# ---------------------------------------------------------------------------


class TestShortCircuits:
    async def test_empty_input_returns_empty_no_api_call(self) -> None:
        f = _make_filter()
        mock_client = MagicMock()
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, [])

        assert result == []
        assert stats.input_count == 0
        mock_client.post.assert_not_called()

    async def test_all_non_asoc_chunks_pass_through_no_api_call(self) -> None:
        f = _make_filter()
        mock_client = MagicMock()
        _inject_mock_client(f, mock_client)

        chunks = [_make_non_asoc_chunk("n1"), _make_non_asoc_chunk("n2")]
        result, stats = await f.filter_chunks(_JWT, chunks)

        assert len(result) == 2
        assert stats.asoc_count == 0
        assert stats.pass_through_count == 2
        assert stats.batches_issued == 0
        mock_client.post.assert_not_called()

    async def test_empty_base_url_no_asoc_chunks_passes_through(self) -> None:
        f = _make_filter(base_url="")
        chunks = [_make_non_asoc_chunk("n1")]
        result, stats = await f.filter_chunks(_JWT, chunks)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Test: auth guard
# ---------------------------------------------------------------------------


class TestAuthGuard:
    async def test_empty_jwt_raises_auth_error(self) -> None:
        f = _make_filter()
        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks("", [_make_asoc_chunk()])

    async def test_blank_jwt_raises_auth_error(self) -> None:
        f = _make_filter()
        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks("   ", [_make_asoc_chunk()])


# ---------------------------------------------------------------------------
# Test: config error
# ---------------------------------------------------------------------------


class TestConfigError:
    async def test_empty_base_url_with_asoc_chunks_raises_config_error(self) -> None:
        f = _make_filter(base_url="")
        # No client set because base_url is empty
        chunks = [_make_asoc_chunk("c1", entity_type="issue", entity_id="issue-1")]
        with pytest.raises(VisibilityFilterConfigError):
            await f.filter_chunks(_JWT, chunks)


# ---------------------------------------------------------------------------
# Test: entity → resource_type mapping
# ---------------------------------------------------------------------------


class TestEntityMapping:
    async def _filter_single(
        self, entity_type: str, entity_id: str, *, visible: bool
    ) -> list[Any]:
        f = _make_filter()
        # For root types, entity_id is the parent id
        # For child types, parent_entity_id is needed
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

        mock_client = AsyncMock()
        visible_ids = [entity_id] if visible else []
        mock_client.post.return_value = _mock_response(200, {"ids": visible_ids})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, [chunk])
        return result

    async def test_root_entity_uses_own_id(self) -> None:
        """issue entity_id is used as the auth key directly."""
        f = _make_filter()
        chunk = _make_asoc_chunk(entity_type="issue", entity_id="issue-42")
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-42"]})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 1
        # Verify the correct resource_type and id were sent
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        assert body["resource_type"] == "issue"
        assert "issue-42" in body["ids"]

    async def test_child_entity_uses_parent_id(self) -> None:
        """comment uses parent_entity_id (the issue id) as the auth key."""
        f = _make_filter()
        chunk = _make_asoc_chunk(
            entity_type="comment",
            entity_id="comment-1",
            parent_entity_id="issue-99",
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-99"]})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 1
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        assert body["resource_type"] == "issue"
        assert "issue-99" in body["ids"]

    async def test_quality_gate_maps_to_project_resource(self) -> None:
        result = await self._filter_single("quality_gate", "proj-1", visible=True)
        assert len(result) == 1

    async def test_gate_alias_maps_to_project_resource(self) -> None:
        result = await self._filter_single("gate", "proj-1", visible=True)
        assert len(result) == 1

    async def test_sbom_maps_to_layer_resource(self) -> None:
        result = await self._filter_single("sbom", "layer-1", visible=True)
        assert len(result) == 1

    async def test_scan_result_maps_to_scan_resource(self) -> None:
        """scan_result entity_type must map to resource_type 'scan' (ASOC contract §1.1)."""
        f = _make_filter()
        chunk = _make_asoc_chunk(entity_type="scan_result", entity_id="scan-1")
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["scan-1"]})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 1
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        # ASOC §1.1: resource_type must be "scan", NOT "scan_result"
        assert body["resource_type"] == "scan"
        assert body["resource_type"] != "scan_result"

    async def test_unknown_entity_type_is_dropped(self) -> None:
        f = _make_filter()
        # Unknown entity type → _resolve_parent_id returns None → dropped
        chunk = _make_asoc_chunk(entity_type="unknown_type", entity_id="x-1")
        # Even if api would say visible, the chunk is dropped before the API call
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["x-1"]})
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, [chunk])
        # The unknown chunk is in "dropped_malformed" and never sent to API,
        # so if there are no other ASOC chunks, it short-circuits.
        assert len(result) == 0

    async def test_missing_parent_id_for_child_is_dropped(self) -> None:
        f = _make_filter()
        # comment without parent_entity_id → dropped
        chunk = _make_asoc_chunk(
            entity_type="comment",
            entity_id="c-1",
            parent_entity_id=None,  # missing
        )
        # Remove parent_entity_id from metadata
        chunk["memory"]["metadata"].pop("parent_entity_id", None)

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-1"]})
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 0

    async def test_sbom_with_parent_groups_under_layer_resource(self) -> None:
        """sbom is a child entity — it must group under resource_type 'layer' via parent_id.

        Regression guard: sbom must NOT be sent as a standalone 'sbom' resource_type
        (ASOC §1.1 — sbom is not a valid resource_type; sbom chunks use parent_entity_id
        pointing at the parent layer).
        """
        f = _make_filter()
        # sbom chunk with a valid parent layer id
        chunk = _make_asoc_chunk(
            entity_type="sbom",
            entity_id="sbom-1",
            parent_entity_id="layer-99",
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["layer-99"]})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 1
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        # Must be "layer", never "sbom"
        assert body["resource_type"] == "layer"
        assert body["resource_type"] != "sbom"
        assert "layer-99" in body["ids"]

    async def test_sbom_without_parent_id_is_dropped(self) -> None:
        """sbom chunk without parent_entity_id must be dropped (fail-closed).

        sbom is a child entity — if parent_entity_id is absent, there is no
        auth key to look up, so the chunk is silently dropped.
        This guards against sbom being sent as a standalone 'sbom' resource_type.
        """
        f = _make_filter()
        chunk = _make_asoc_chunk(
            entity_type="sbom",
            entity_id="sbom-orphan",
            parent_entity_id=None,  # deliberately absent
        )
        # Ensure parent_entity_id is not in metadata
        chunk["memory"]["metadata"].pop("parent_entity_id", None)

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["sbom-orphan"]})
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, [chunk])
        # Dropped malformed (no parent_entity_id) — never sent to ASOC as resource_type sbom
        assert len(result) == 0
        mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Test: grouping, batching, parallel
# ---------------------------------------------------------------------------


class TestGroupingAndBatching:
    async def test_grouping_multiple_resource_types(self) -> None:
        """Chunks of different resource_types lead to separate POST calls."""
        f = _make_filter()
        chunks = [
            _make_asoc_chunk("c1", "issue", "issue-1"),
            _make_asoc_chunk("c2", "project", "proj-1"),
            _make_asoc_chunk("c3", "layer", "layer-1"),
        ]
        mock_client = AsyncMock()
        # Each POST returns visible_ids for the type asked
        mock_client.post.return_value = _mock_response(
            200, {"ids": ["issue-1", "proj-1", "layer-1"]}
        )
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, chunks)
        # 3 POST calls: one per resource_type
        assert mock_client.post.call_count == 3
        assert len(result) == 3

    async def test_batching_above_batch_size(self) -> None:
        """101 IDs with batch_size=100 → 2 POST calls for that resource type."""
        f = _make_filter(batch_size=100)
        chunks = [_make_asoc_chunk(f"c{i}", "issue", f"issue-{i}") for i in range(101)]
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(
            200, {"ids": [f"issue-{i}" for i in range(101)]}
        )
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, chunks)
        assert mock_client.post.call_count == 2
        assert stats.batches_issued == 2
        assert len(result) == 101

    async def test_parallel_across_resource_types(self) -> None:
        """asyncio.gather is used across resource types — verify calls complete."""
        calls: list[str] = []

        async def _mock_post(path: str, *, json: dict, headers: dict) -> MagicMock:
            calls.append(json["resource_type"])
            return _mock_response(200, {"ids": json["ids"]})

        f = _make_filter()
        chunks = [
            _make_asoc_chunk("c1", "issue", "issue-1"),
            _make_asoc_chunk("c2", "project", "proj-1"),
        ]
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_mock_post)
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, chunks)
        assert set(calls) == {"issue", "project"}
        assert len(result) == 2

    async def test_visible_ids_merge(self) -> None:
        """Two batches for the same resource_type merge their visible_ids."""
        f = _make_filter(batch_size=2)
        # 4 issues → 2 batches → responses have 2 ids each
        chunks = [_make_asoc_chunk(f"c{i}", "issue", f"issue-{i}") for i in range(4)]

        mock_client = AsyncMock()
        # First call returns issues 0-1, second returns issues 2-3
        mock_client.post.side_effect = [
            _mock_response(200, {"ids": ["issue-0", "issue-1"]}),
            _mock_response(200, {"ids": ["issue-2", "issue-3"]}),
        ]
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, chunks)
        assert len(result) == 4

    async def test_output_preserves_original_order(self) -> None:
        """The output list must be in the same order as the input."""
        f = _make_filter()
        chunks = [
            _make_non_asoc_chunk("n1"),
            _make_asoc_chunk("a1", "issue", "issue-1"),
            _make_non_asoc_chunk("n2"),
            _make_asoc_chunk("a2", "issue", "issue-2"),
        ]
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-1", "issue-2"]})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, chunks)
        ids = [r["chunk_id"] for r in result]
        assert ids == ["n1", "a1", "n2", "a2"]

    async def test_chunks_not_in_visible_ids_are_dropped(self) -> None:
        f = _make_filter()
        chunks = [
            _make_asoc_chunk("keep", "issue", "issue-allowed"),
            _make_asoc_chunk("drop", "issue", "issue-denied"),
        ]
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-allowed"]})
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, chunks)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "keep"
        assert stats.dropped_count == 1


# ---------------------------------------------------------------------------
# Test: HTTP error handling
# ---------------------------------------------------------------------------


class TestHttpErrors:
    async def test_401_raises_auth_error_no_retry(self) -> None:
        f = _make_filter(retry_attempts=2)
        chunk = _make_asoc_chunk()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(401)
        _inject_mock_client(f, mock_client)

        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks(_JWT, [chunk])
        # 401 → no retry (called exactly once)
        assert mock_client.post.call_count == 1

    async def test_403_raises_auth_error_no_retry(self) -> None:
        f = _make_filter(retry_attempts=2)
        chunk = _make_asoc_chunk()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(403)
        _inject_mock_client(f, mock_client)

        with pytest.raises(VisibilityFilterAuthError):
            await f.filter_chunks(_JWT, [chunk])
        assert mock_client.post.call_count == 1

    async def test_400_raises_protocol_error_no_retry(self) -> None:
        f = _make_filter(retry_attempts=2)
        chunk = _make_asoc_chunk()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(400, text="bad request")
        _inject_mock_client(f, mock_client)

        with pytest.raises(VisibilityFilterProtocolError):
            await f.filter_chunks(_JWT, [chunk])
        assert mock_client.post.call_count == 1

    async def test_500_retries_then_raises_unavailable(self) -> None:
        """retry_attempts=2 → 3 total calls for 500 responses."""
        f = _make_filter(retry_attempts=2)
        chunk = _make_asoc_chunk()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(500)
        _inject_mock_client(f, mock_client)

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(VisibilityFilterUnavailableError),
        ):
            await f.filter_chunks(_JWT, [chunk])

        assert mock_client.post.call_count == 3

    async def test_network_error_retries_then_raises_unavailable(self) -> None:
        """RequestError → retry then raise VisibilityFilterUnavailableError."""
        import httpx

        f = _make_filter(retry_attempts=2)
        chunk = _make_asoc_chunk()
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        _inject_mock_client(f, mock_client)

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(VisibilityFilterUnavailableError),
        ):
            await f.filter_chunks(_JWT, [chunk])

        assert mock_client.post.call_count == 3

    async def test_503_then_200_succeeds_after_retry(self) -> None:
        f = _make_filter(retry_attempts=2)
        chunk = _make_asoc_chunk("c1", "issue", "issue-1")
        mock_client = AsyncMock()
        mock_client.post.side_effect = [
            _mock_response(503),
            _mock_response(200, {"ids": ["issue-1"]}),
        ]
        _inject_mock_client(f, mock_client)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result, _ = await f.filter_chunks(_JWT, [chunk])

        assert len(result) == 1
        assert mock_client.post.call_count == 2

    async def test_malformed_response_missing_ids_raises_protocol_error(
        self,
    ) -> None:
        f = _make_filter()
        chunk = _make_asoc_chunk()
        mock_client = AsyncMock()
        # Response missing required 'ids' field
        mock_client.post.return_value = _mock_response(200, {"something_else": []})
        _inject_mock_client(f, mock_client)

        with pytest.raises(VisibilityFilterProtocolError):
            await f.filter_chunks(_JWT, [chunk])


# ---------------------------------------------------------------------------
# Test: overall budget timeout
# ---------------------------------------------------------------------------


class TestBudgetTimeout:
    async def test_overall_budget_timeout_raises_unavailable(self) -> None:
        """Slow mock + very low budget → TimeoutError → VisibilityFilterUnavailableError."""

        async def _slow_post(*args: Any, **kwargs: Any) -> MagicMock:
            await asyncio.sleep(10)  # longer than budget
            return _mock_response(200, {"ids": []})

        f = _make_filter(timeout_seconds=0.01)  # 10ms budget
        chunk = _make_asoc_chunk()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_slow_post)
        _inject_mock_client(f, mock_client)

        with pytest.raises(VisibilityFilterUnavailableError, match="budget exceeded"):
            await f.filter_chunks(_JWT, [chunk])


# ---------------------------------------------------------------------------
# Test: health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_health_check_returns_false_when_base_url_empty(self) -> None:
        f = _make_filter(base_url="")
        result = await f.health_check()
        assert result is False

    async def test_health_check_returns_true_on_405(self) -> None:
        f = _make_filter()
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(405)
        _inject_mock_client(f, mock_client)

        result = await f.health_check()
        assert result is True

    async def test_health_check_returns_true_on_401(self) -> None:
        f = _make_filter()
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(401)
        _inject_mock_client(f, mock_client)

        result = await f.health_check()
        assert result is True

    async def test_health_check_returns_false_on_404(self) -> None:
        f = _make_filter()
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(404)
        _inject_mock_client(f, mock_client)

        result = await f.health_check()
        assert result is False

    async def test_health_check_returns_false_on_connect_error(self) -> None:
        import httpx

        f = _make_filter()
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        _inject_mock_client(f, mock_client)

        result = await f.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# Test: stats object
# ---------------------------------------------------------------------------


class TestStats:
    async def test_stats_object_populated_correctly(self) -> None:
        f = _make_filter(batch_size=100)
        chunks = [
            _make_non_asoc_chunk("n1"),
            _make_asoc_chunk("a1", "issue", "issue-1"),
            _make_asoc_chunk("a2", "issue", "issue-2"),
        ]
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-1"]})
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, chunks)

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
        f = _make_filter()
        mock_client = MagicMock()
        _inject_mock_client(f, mock_client)

        chunks = [_make_non_asoc_chunk("n1"), _make_non_asoc_chunk("n2")]
        result, stats = await f.filter_chunks(_JWT, chunks)

        assert stats.asoc_count == 0
        assert stats.batches_issued == 0
        assert stats.pass_through_count == 2
        assert stats.dropped_count == 0
        mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Test: from_settings
# ---------------------------------------------------------------------------


class TestFromSettings:
    def test_from_settings_constructs_correctly(self) -> None:
        from metatron.core.config import Settings

        settings = Settings(
            ASOC_BASE_URL="https://asoc.test.com",
            METATRON_ASOC_VISIBILITY_FILTER_TIMEOUT_SECONDS="7.0",
            METATRON_ASOC_VISIBILITY_FILTER_BATCH_SIZE="50",
            METATRON_ASOC_VISIBILITY_FILTER_RETRY_ATTEMPTS="1",
        )
        f = AsocVisibilityFilter.from_settings(settings)
        assert f.base_url == "https://asoc.test.com"
        assert f.timeout_seconds == 7.0
        assert f.batch_size == 50
        assert f.retry_attempts == 1

    def test_from_settings_empty_url_no_client(self) -> None:
        from metatron.core.config import Settings

        settings = Settings(ASOC_BASE_URL="")
        f = AsocVisibilityFilter.from_settings(settings)
        assert f.base_url == ""
        assert f._client is None


# ---------------------------------------------------------------------------
# Test: aclose
# ---------------------------------------------------------------------------


class TestAclose:
    async def test_aclose_closes_httpx_client(self) -> None:
        f = _make_filter()
        mock_client = AsyncMock()
        _inject_mock_client(f, mock_client)

        await f.aclose()

        mock_client.aclose.assert_called_once()
        assert f._client is None

    async def test_aclose_idempotent_no_client(self) -> None:
        f = _make_filter(base_url="")
        # No client — should not raise
        await f.aclose()


# ---------------------------------------------------------------------------
# Test: Qdrant payload layout variant (nested under 'payload')
# ---------------------------------------------------------------------------


class TestMetadataExtraction:
    async def test_nested_payload_metadata_extracted(self) -> None:
        """Older Qdrant payloads nest metadata under memory.payload.metadata."""
        f = _make_filter()
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
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"ids": ["issue-1"]})
        _inject_mock_client(f, mock_client)

        result, _ = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 1

    async def test_source_type_from_nested_payload(self) -> None:
        """source_type resolved from memory.payload.source_type when not in memory."""
        f = _make_filter()
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
        mock_client = MagicMock()
        _inject_mock_client(f, mock_client)

        result, stats = await f.filter_chunks(_JWT, [chunk])
        assert len(result) == 1
        assert stats.pass_through_count == 1
        mock_client.post.assert_not_called()
