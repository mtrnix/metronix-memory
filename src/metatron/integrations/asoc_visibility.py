"""ASOC visibility filter — post-retrieval RBAC callback via MCP.

After retrieval, T4 (chat orchestrator) calls ``AsocVisibilityFilter.filter_chunks``
with the authenticated user's session_id and the list of ``MergedResult`` chunks.
This module calls the ``asoc_visibility_filter`` MCP tool (user mode) via
``AsocMcpClient.invoke`` and drops any chunk whose parent entity is NOT in the
response's ``ids``.

Design invariants (ASOC_API_CONTRACT.md §3.2 / §1.1):
- **Hard-fail mode** — any MCP failure raises a typed ``VisibilityFilterError``.
  Caller (T4) catches the base type and emits SSE ``error: visibility_filter_failed``
  without invoking the LLM.  There is NO degraded-pass path.
- **5 s overall budget** enforced via ``asyncio.wait_for`` wrapping the full operation.
- **Parallel across resource types, sequential within** (batch iteration per type).
- **Pass-through for non-ASOC chunks** — never calls the MCP tool for non-ASOC source.
- **No caching** of visible IDs per-user (Phase 2 work, not here).
- **Empty session_id** raises ``VisibilityFilterAuthError`` immediately (no network call).
- **McpAuthError** → ``VisibilityFilterAuthError`` (not retried).
- **McpToolNotAllowedError** → ``VisibilityFilterConfigError`` (config bug, not retried).
- **McpUnavailableError / McpProtocolError** → retried up to ``retry_attempts`` times.

Exception hierarchy (all in this module, not in ``core/exceptions.py``):
    VisibilityFilterError
    ├── VisibilityFilterConfigError  — mcp_client not configured / tool not allowed
    ├── VisibilityFilterAuthError    — McpAuthError or empty session_id
    ├── VisibilityFilterUnavailableError — McpUnavailableError after retries
    └── VisibilityFilterProtocolError   — McpProtocolError / malformed response / missing ids field
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from metatron.core.config import Settings
    from metatron.integrations.asoc_mcp_client import AsocMcpClient
    from metatron.retrieval.channels import MergedResult

__all__ = [
    "AsocVisibilityFilter",
    "VisibilityFilterAuthError",
    "VisibilityFilterConfigError",
    "VisibilityFilterError",
    "VisibilityFilterProtocolError",
    "VisibilityFilterStats",
    "VisibilityFilterUnavailableError",
]

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class VisibilityFilterError(Exception):
    """Base — caught by T4's chat handler."""


class VisibilityFilterConfigError(VisibilityFilterError):
    """mcp_client not configured, or asoc_visibility_filter tool not in whitelist."""


class VisibilityFilterAuthError(VisibilityFilterError):
    """McpAuthError — session bad, or empty session_id passed."""


class VisibilityFilterUnavailableError(VisibilityFilterError):
    """McpUnavailableError after retries, or overall budget exceeded."""


class VisibilityFilterProtocolError(VisibilityFilterError):
    """McpProtocolError, malformed response, or missing ids field."""


# ---------------------------------------------------------------------------
# Stats model
# ---------------------------------------------------------------------------


class VisibilityFilterStats(BaseModel):
    """Per-call statistics returned alongside filtered results."""

    input_count: int
    asoc_count: int
    pass_through_count: int
    dropped_count: int
    output_count: int
    resource_type_counts: dict[str, int]
    batches_issued: int
    elapsed_ms: float


# ---------------------------------------------------------------------------
# Entity → resource_type mapping
# ---------------------------------------------------------------------------

_ENTITY_TO_RESOURCE_TYPE: dict[str, str] = {
    "issue": "issue",
    "comment": "issue",
    "issue_history": "issue",
    "scan_result": "scan",  # ASOC contract §1.1: resource_type is "scan", not "scan_result"
    "layer": "layer",
    "sbom": "layer",  # sbom groups under "layer" via parent_id (no standalone sbom resource_type)
    "dependency": "layer",
    "project": "project",
    "quality_gate": "project",
    "gate": "gate",  # ASOC contract §1.1: "gate" is a valid resource_type
    "event": "project",
}

# Child entities: look up parent_entity_id from metadata
_PARENT_ENTITY_TYPES: frozenset[str] = frozenset(
    {"comment", "issue_history", "sbom", "dependency", "quality_gate", "gate", "event"}
)

# Root entities: use their own entity_id as the authorization key
_ROOT_ENTITY_TYPES: frozenset[str] = frozenset({"issue", "scan_result", "layer", "project"})

# MCP tool name for visibility filtering (user-mode call)
_VISIBILITY_FILTER_TOOL = "asoc_visibility_filter"


# ---------------------------------------------------------------------------
# Helper: empty stats
# ---------------------------------------------------------------------------


def _empty_stats(elapsed_ms: float = 0.0) -> VisibilityFilterStats:
    return VisibilityFilterStats(
        input_count=0,
        asoc_count=0,
        pass_through_count=0,
        dropped_count=0,
        output_count=0,
        resource_type_counts={},
        batches_issued=0,
        elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Helper: parse MCP content blocks into a dict
# ---------------------------------------------------------------------------


def _parse_mcp_content(content: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract a JSON dict from a list of MCP content blocks.

    Handles two content block shapes:
    - ``{"type": "json", "data": {...}}``
    - ``{"type": "text", "text": "<json string>"}``

    Raises:
        VisibilityFilterProtocolError: No parseable JSON block found.
    """
    import json

    for block in content:
        if block.get("type") == "json":
            data = block.get("data")
            if isinstance(data, dict):
                return data

        text = block.get("text")
        if isinstance(text, str) and text.strip().startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue

    raise VisibilityFilterProtocolError(
        f"no parseable JSON block in asoc_visibility_filter response: {content!r}"
    )


# ---------------------------------------------------------------------------
# AsocVisibilityFilter
# ---------------------------------------------------------------------------


class AsocVisibilityFilter:
    """Post-retrieval RBAC filter via ASOC's ``asoc_visibility_filter`` MCP tool.

    Calls the tool in user mode (session_id forwarded as ``X-ASOC-Session``),
    grouping chunks by resource_type and issuing one MCP call per group (parallel
    across types, sequential per batch within a type).

    Hard-fail mode: any MCP failure raises ``VisibilityFilterError``.  Caller
    (T4 chat orchestrator) catches the base type and emits SSE
    ``error: visibility_filter_failed`` without invoking the LLM.

    NO caching (ASOC_API_CONTRACT.md §3 — Phase 2).
    NO degraded fallback (security control).

    Args:
        mcp_client: User-mode ``AsocMcpClient`` instance (shared from app.state).
            ``None`` disables the filter — ``filter_chunks()`` with ASOC chunks
            raises ``VisibilityFilterConfigError``.
        timeout_seconds: Hard overall budget for ``filter_chunks()``.  Enforced via
            ``asyncio.wait_for``.  Defaults to 5.0 (ASOC_API_CONTRACT.md §3.2).
        batch_size: Maximum IDs per single ``asoc_visibility_filter`` tool call.
        retry_attempts: Retry attempts on ``McpUnavailableError`` / ``McpProtocolError``
            per batch.  ``McpAuthError`` and ``ToolNotAllowedError`` are never retried.
            ``0`` = no retries (one attempt only).
    """

    def __init__(
        self,
        mcp_client: AsocMcpClient | None,
        *,
        timeout_seconds: float = 5.0,
        batch_size: int = 100,
        retry_attempts: int = 2,
    ) -> None:
        self._mcp_client = mcp_client
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self.retry_attempts = retry_attempts

    @classmethod
    def from_settings(
        cls, settings: Settings, mcp_client: AsocMcpClient | None
    ) -> AsocVisibilityFilter:
        """Construct from app settings and a pre-built user-mode MCP client."""
        return cls(
            mcp_client=mcp_client,
            timeout_seconds=settings.asoc_visibility_filter_timeout_seconds,
            batch_size=settings.asoc_visibility_filter_batch_size,
            retry_attempts=settings.asoc_visibility_filter_retry_attempts,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def filter_chunks(
        self,
        session_id: str,
        merged_results: list[MergedResult],
    ) -> tuple[list[MergedResult], VisibilityFilterStats]:
        """Filter chunks to those the user is allowed to see.

        Returns:
            ``(filtered_results, stats)`` where ``filtered_results`` preserves
            the original ordering of allowed chunks.

        Raises:
            VisibilityFilterAuthError: Empty or blank session_id.
            VisibilityFilterConfigError: ASOC chunks present but mcp_client is None,
                or asoc_visibility_filter tool not in whitelist.
            VisibilityFilterUnavailableError: MCP unavailable after retries, or budget exceeded.
            VisibilityFilterProtocolError: Malformed response or unexpected error.
        """
        if not session_id or not session_id.strip():
            raise VisibilityFilterAuthError("empty session_id")

        if not merged_results:
            return [], _empty_stats()

        start = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._do_filter(session_id, merged_results, start),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            logger.error(
                "asoc.visibility_filter.budget_exceeded",
                timeout_seconds=self.timeout_seconds,
                elapsed_ms=elapsed_ms,
            )
            raise VisibilityFilterUnavailableError(
                f"5s budget exceeded ({elapsed_ms:.0f}ms)"
            ) from exc

    async def health_check(self) -> bool:
        """Return True if the MCP client is configured, False otherwise.

        With MCP transport there is no cheap unauthenticated probe like the REST
        GET.  We simply check whether the client is present.  Actual liveness is
        verified on the first real ``filter_chunks`` call.
        """
        return self._mcp_client is not None

    # ------------------------------------------------------------------
    # Internal: full filtering pipeline
    # ------------------------------------------------------------------

    async def _do_filter(
        self,
        session_id: str,
        merged_results: list[Any],
        start: float,
    ) -> tuple[list[Any], VisibilityFilterStats]:
        # Split into ASOC vs pass-through, group ASOC by resource_type.
        asoc_by_resource, pass_through, dropped_malformed = self._group_by_resource_type(
            merged_results
        )

        # Count chunks by resource_type for stats.
        resource_type_counts = {rt: len(items) for rt, items in asoc_by_resource.items() if items}
        total_asoc = sum(len(items) for items in asoc_by_resource.values())

        # Short-circuit: no ASOC chunks at all.
        if total_asoc == 0:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            stats = VisibilityFilterStats(
                input_count=len(merged_results),
                asoc_count=0,
                pass_through_count=len(pass_through),
                dropped_count=len(dropped_malformed),
                output_count=len(pass_through),
                resource_type_counts={},
                batches_issued=0,
                elapsed_ms=elapsed_ms,
            )
            return pass_through, stats

        # ASOC chunks present — require mcp_client.
        if self._mcp_client is None:
            raise VisibilityFilterConfigError("AsocMcpClient not configured")

        # Parallel fetch across resource types.
        resource_types = [rt for rt, items in asoc_by_resource.items() if items]
        tasks = [
            self._fetch_visible_ids(
                session_id,
                rt,
                [parent_id for _, parent_id in asoc_by_resource[rt]],
            )
            for rt in resource_types
        ]
        results_per_type: list[list[str]] = await asyncio.gather(*tasks)

        # Build allowed set: {(resource_type, parent_id)}.
        allowed_set: set[tuple[str, str]] = set()
        for rt, visible_ids in zip(resource_types, results_per_type, strict=True):
            for vid in visible_ids:
                allowed_set.add((rt, vid))

        # Filter merged_results in original order.
        output: list[Any] = []
        for mr in merged_results:
            metadata = self._extract_metadata(mr)
            source_type = self._extract_source_type(mr)
            if source_type != "asoc":
                output.append(mr)  # non-ASOC pass-through
                continue
            parent = self._resolve_parent_id(metadata)
            if parent is None:
                # Malformed / unknown entity → fail-closed (drop silently).
                continue
            if parent in allowed_set:
                output.append(mr)
            # else: drop (not in allowed ids)

        # Compute batches_issued.
        batches_issued = sum(
            (len(items) + self.batch_size - 1) // self.batch_size
            for rt, items in asoc_by_resource.items()
            if items
        )

        elapsed_ms = (time.monotonic() - start) * 1000.0
        stats = VisibilityFilterStats(
            input_count=len(merged_results),
            asoc_count=total_asoc,
            pass_through_count=len(pass_through),
            dropped_count=len(merged_results) - len(output),
            output_count=len(output),
            resource_type_counts=resource_type_counts,
            batches_issued=batches_issued,
            elapsed_ms=elapsed_ms,
        )
        logger.info(
            "asoc.visibility_filter.done",
            input_count=stats.input_count,
            output_count=stats.output_count,
            dropped_count=stats.dropped_count,
            elapsed_ms=f"{stats.elapsed_ms:.1f}",
        )
        return output, stats

    # ------------------------------------------------------------------
    # Internal: MCP fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_visible_ids(
        self, session_id: str, resource_type: str, ids: list[str]
    ) -> list[str]:
        """Fetch visible IDs for one resource_type, batching sequentially."""
        all_visible: set[str] = set()
        for i in range(0, len(ids), self.batch_size):
            batch = ids[i : i + self.batch_size]
            visible = await self._invoke_one_batch(session_id, resource_type, batch)
            all_visible.update(visible)
        return list(all_visible)

    async def _invoke_one_batch(
        self, session_id: str, resource_type: str, ids: list[str]
    ) -> list[str]:
        """Invoke the asoc_visibility_filter MCP tool for one batch, with retry.

        Retried on ``McpUnavailableError`` and ``McpProtocolError`` (transient).
        NOT retried on ``McpAuthError`` (auth failures aren't transient) or
        ``ToolNotAllowedError`` (config bug, fail fast).

        Raises:
            VisibilityFilterAuthError: McpAuthError — session bad (no retry).
            VisibilityFilterConfigError: ToolNotAllowedError — tool not in whitelist (no retry).
            VisibilityFilterUnavailableError: McpUnavailableError after all retries.
            VisibilityFilterProtocolError: Malformed response after all retries.
        """
        from metatron.integrations.asoc_mcp_client import (
            McpAuthError,
            McpProtocolError,
            McpUnavailableError,
            ToolNotAllowedError,
        )

        assert self._mcp_client is not None  # invariant: caller already checked
        last_exc: Exception = VisibilityFilterUnavailableError("no attempts made")

        for attempt in range(self.retry_attempts + 1):
            try:
                result = await self._mcp_client.invoke(
                    session_id=session_id,
                    tool_name=_VISIBILITY_FILTER_TOOL,
                    arguments={"resource_type": resource_type, "ids": ids},
                )
            except McpAuthError as exc:
                # Auth failures are not transient — fail immediately.
                raise VisibilityFilterAuthError(str(exc)) from exc
            except ToolNotAllowedError as exc:
                # Config bug — asoc_visibility_filter not in whitelist.
                raise VisibilityFilterConfigError(
                    f"asoc_visibility_filter not in MCP whitelist: {exc}"
                ) from exc
            except McpUnavailableError as exc:
                last_exc = VisibilityFilterUnavailableError(str(exc))
                if attempt < self.retry_attempts:
                    await asyncio.sleep(2.0**attempt)  # 1 s, 2 s
                    continue
                raise last_exc from exc
            except McpProtocolError as exc:
                last_exc = VisibilityFilterProtocolError(str(exc))
                if attempt < self.retry_attempts:
                    await asyncio.sleep(2.0**attempt)
                    continue
                raise last_exc from exc
            except Exception as exc:
                # Unknown error — treat as unavailable.
                last_exc = VisibilityFilterUnavailableError(f"unexpected: {exc}")
                if attempt < self.retry_attempts:
                    await asyncio.sleep(2.0**attempt)
                    continue
                raise last_exc from exc

            # Parse response content blocks.
            try:
                payload = _parse_mcp_content(result.content)
            except VisibilityFilterProtocolError:
                raise

            ids_value = payload.get("ids")
            if not isinstance(ids_value, list):
                raise VisibilityFilterProtocolError(
                    f"asoc_visibility_filter response missing 'ids' list: {payload!r}"
                )
            return [str(v) for v in ids_value if isinstance(v, str)]

        raise last_exc

    # ------------------------------------------------------------------
    # Internal: grouping and metadata extraction
    # ------------------------------------------------------------------

    def _group_by_resource_type(
        self, merged_results: list[Any]
    ) -> tuple[dict[str, list[tuple[str, str]]], list[Any], list[Any]]:
        """Split merged_results into ASOC (by resource_type), pass-through, dropped.

        Returns:
            ``(asoc_by_resource, pass_through, dropped_malformed)``
            where ``asoc_by_resource[resource_type]`` is a list of
            ``(chunk_id, parent_id)`` tuples.
        """
        asoc_by_resource: dict[str, list[tuple[str, str]]] = {}
        pass_through: list[Any] = []
        dropped_malformed: list[Any] = []

        for mr in merged_results:
            metadata = self._extract_metadata(mr)
            source_type = self._extract_source_type(mr)

            if source_type != "asoc":
                pass_through.append(mr)
                continue

            parent = self._resolve_parent_id(metadata)
            if parent is None:
                dropped_malformed.append(mr)
                continue

            resource_type, parent_id = parent
            chunk_id = mr.get("chunk_id", "") if isinstance(mr, dict) else ""
            asoc_by_resource.setdefault(resource_type, []).append((chunk_id, parent_id))

        return asoc_by_resource, pass_through, dropped_malformed

    def _resolve_parent_id(self, metadata: dict[str, Any]) -> tuple[str, str] | None:
        """Return ``(resource_type, parent_id)`` or ``None`` if unresolvable.

        For root entity types (issue, scan_result, layer, project), the parent_id
        is the entity's own ``entity_id`` (note: scan_result maps to resource_type "scan").
        For child entity types (comment, issue_history, sbom, dependency,
        quality_gate, gate, event), the parent_id comes from ``parent_entity_id``
        field added by T1's metadata builder extension.
        Note: sbom is a child type — it groups under resource_type "layer" via parent_id.
        """
        entity_type = metadata.get("entity_type")
        if not entity_type:
            return None

        resource_type = _ENTITY_TO_RESOURCE_TYPE.get(entity_type)
        if resource_type is None:
            logger.warning("asoc.visibility.unknown_entity_type", entity_type=entity_type)
            return None

        if entity_type in _ROOT_ENTITY_TYPES:
            parent_id = metadata.get("entity_id")
        elif entity_type in _PARENT_ENTITY_TYPES:
            parent_id = metadata.get("parent_entity_id")
        else:
            return None

        if not parent_id:
            logger.warning(
                "asoc.visibility.missing_parent_id",
                entity_type=entity_type,
                entity_id=metadata.get("entity_id"),
            )
            return None

        return resource_type, str(parent_id)

    def _extract_metadata(self, mr: Any) -> dict[str, Any]:
        """Navigate MergedResult to find Document.metadata.

        Newer Qdrant payload: ``mr['memory']['metadata']``.
        Older flattened: ``mr['memory']['payload']['metadata']``.
        """
        if not isinstance(mr, dict):
            return {}
        memory = mr.get("memory", {})
        if not isinstance(memory, dict):
            return {}
        md = memory.get("metadata")
        if isinstance(md, dict):
            return md
        payload = memory.get("payload", {})
        if isinstance(payload, dict):
            md2 = payload.get("metadata")
            if isinstance(md2, dict):
                return md2
        return {}

    def _extract_source_type(self, mr: Any) -> str:
        """Extract ``source_type`` from a MergedResult dict."""
        if not isinstance(mr, dict):
            return ""
        memory = mr.get("memory", {})
        if not isinstance(memory, dict):
            return ""
        st = memory.get("source_type")
        if isinstance(st, str) and st:
            return st
        payload = memory.get("payload", {})
        if isinstance(payload, dict):
            st2 = payload.get("source_type")
            if isinstance(st2, str):
                return st2
        return ""
