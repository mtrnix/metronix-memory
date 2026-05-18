"""ASOC visibility filter — post-retrieval RBAC callback.

After retrieval, T4 (chat orchestrator) calls ``AsocVisibilityFilter.filter_chunks``
with the authenticated user's JWT and the list of ``MergedResult`` chunks.  This
module calls ``POST /api/v1/visibility/filter`` on the ASOC REST API and drops
any chunk whose parent entity is NOT in the response's ``visible_ids``.

Design invariants (Confluence §5):
- **Hard-fail mode** — any HTTP failure raises a typed ``VisibilityFilterError``.
  Caller (T4) catches the base type and emits SSE ``error: visibility_filter_failed``
  without invoking the LLM.  There is NO degraded-pass path.
- **5 s overall budget** enforced via ``asyncio.wait_for`` wrapping the full operation.
- **Parallel across resource types, sequential within** (batch iteration per type).
- **Pass-through for non-ASOC chunks** — never calls the API for non-ASOC source.
- **No caching** of ``visible_ids`` per-user (Phase 2 work, not here).
- **Empty JWT** raises ``VisibilityFilterAuthError`` immediately (no network call).

Exception hierarchy (all in this module, not in ``core/exceptions.py``):
    VisibilityFilterError
    ├── VisibilityFilterConfigError  — asoc_base_url empty AND ASOC chunks present
    ├── VisibilityFilterAuthError    — 401/403 or empty JWT
    ├── VisibilityFilterUnavailableError — network / timeout / 5xx after retries
    └── VisibilityFilterProtocolError   — 4xx (non-auth), malformed JSON, missing field
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Literal

import httpx
import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from metatron.core.config import Settings
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
    """asoc_base_url empty AND ASOC chunks present."""


class VisibilityFilterAuthError(VisibilityFilterError):
    """401/403 — JWT bad, or empty JWT passed."""


class VisibilityFilterUnavailableError(VisibilityFilterError):
    """Network, timeout, 5xx after retries."""


class VisibilityFilterProtocolError(VisibilityFilterError):
    """400/422/malformed JSON/missing visible_ids."""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class _FilterRequest(BaseModel):
    resource_type: Literal["issue", "scan_result", "layer", "project"]
    ids: list[str]


class _FilterResponse(BaseModel):
    visible_ids: list[str]


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

_ENTITY_TO_RESOURCE_TYPE: dict[str, Literal["issue", "scan_result", "layer", "project"]] = {
    "issue": "issue",
    "comment": "issue",
    "issue_history": "issue",
    "scan_result": "scan_result",
    "layer": "layer",
    "sbom": "layer",
    "dependency": "layer",
    "project": "project",
    "quality_gate": "project",
    "gate": "project",  # defensive alias (Confluence §4 wording)
    "event": "project",
}

# Child entities: look up parent_entity_id from metadata
_PARENT_ENTITY_TYPES: frozenset[str] = frozenset(
    {"comment", "issue_history", "sbom", "dependency", "quality_gate", "gate", "event"}
)

# Root entities: use their own entity_id as the authorization key
_ROOT_ENTITY_TYPES: frozenset[str] = frozenset({"issue", "scan_result", "layer", "project"})


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
# AsocVisibilityFilter
# ---------------------------------------------------------------------------


class AsocVisibilityFilter:
    """Post-retrieval RBAC filter calling ASOC's visibility/filter endpoint.

    Hard-fail mode: any HTTP failure raises ``VisibilityFilterError``.  Caller
    (T4 chat orchestrator) catches the base type and emits SSE
    ``error: visibility_filter_failed`` without invoking the LLM.

    NO caching (Confluence §5 — Phase 2).
    NO degraded fallback (security control).

    Args:
        base_url: Base URL of the ASOC REST API (e.g. ``https://asoc.example.com``).
            Empty string disables the filter — ``health_check()`` returns ``False``
            and ``filter_chunks()`` with ASOC chunks raises
            ``VisibilityFilterConfigError``.
        timeout_seconds: Hard overall budget for ``filter_chunks()``.  Enforced via
            ``asyncio.wait_for``.  Defaults to 5.0 (Confluence §5).
        batch_size: Maximum IDs per single visibility/filter POST.
        retry_attempts: Retry attempts on 5xx / network errors per batch.
            ``0`` = no retries (one attempt only).
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        batch_size: int = 100,
        retry_attempts: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self.retry_attempts = retry_attempts
        self._client: httpx.AsyncClient | None = None
        if self.base_url:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=False,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "metatron-asoc-visibility/1.0",
                },
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> AsocVisibilityFilter:
        """Construct from app settings."""
        return cls(
            base_url=settings.asoc_base_url,
            timeout_seconds=settings.asoc_visibility_filter_timeout_seconds,
            batch_size=settings.asoc_visibility_filter_batch_size,
            retry_attempts=settings.asoc_visibility_filter_retry_attempts,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def filter_chunks(
        self,
        user_jwt: str,
        merged_results: list[MergedResult],
    ) -> tuple[list[MergedResult], VisibilityFilterStats]:
        """Filter chunks to those the user is allowed to see.

        Returns:
            ``(filtered_results, stats)`` where ``filtered_results`` preserves
            the original ordering of allowed chunks.

        Raises:
            VisibilityFilterAuthError: Empty or blank JWT.
            VisibilityFilterConfigError: ASOC chunks present but ``asoc_base_url`` empty.
            VisibilityFilterUnavailableError: Network / timeout / 5xx after retries.
            VisibilityFilterProtocolError: Malformed response or unexpected HTTP status.
        """
        if not user_jwt or not user_jwt.strip():
            raise VisibilityFilterAuthError("empty user_jwt")

        if not merged_results:
            return [], _empty_stats()

        start = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._do_filter(user_jwt, merged_results, start),
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
        """Probe the visibility/filter endpoint without a user JWT.

        Returns:
            ``True`` if the endpoint is reachable (405 or 401 are both "server up"),
            ``False`` if ``asoc_base_url`` is empty or any exception occurs.
            Never raises.
        """
        if not self.base_url or not self._client:
            return False
        try:
            response = await asyncio.wait_for(
                self._client.get("/api/v1/visibility/filter"),
                timeout=min(self.timeout_seconds, 2.0),
            )
            # 405 (Method Not Allowed — endpoint exists, no GET) or
            # 401 (needs auth) confirm endpoint is reachable.
            return response.status_code in (401, 405)
        except Exception:
            return False

    async def aclose(self) -> None:
        """Close the internal httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal: full filtering pipeline
    # ------------------------------------------------------------------

    async def _do_filter(
        self,
        user_jwt: str,
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
            # pass_through is the full output; dropped_malformed are excluded.
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

        # ASOC chunks present — require base_url.
        if not self.base_url or not self._client:
            raise VisibilityFilterConfigError("asoc_base_url not configured")

        # Parallel fetch across resource types.
        resource_types = [rt for rt, items in asoc_by_resource.items() if items]
        tasks = [
            self._fetch_visible_ids(
                user_jwt,
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
            # else: drop (not in visible_ids)

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
    # Internal: HTTP fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_visible_ids(
        self, user_jwt: str, resource_type: str, ids: list[str]
    ) -> list[str]:
        """Fetch visible IDs for one resource_type, batching sequentially."""
        all_visible: set[str] = set()
        for i in range(0, len(ids), self.batch_size):
            batch = ids[i : i + self.batch_size]
            visible = await self._post_one_batch(user_jwt, resource_type, batch)
            all_visible.update(visible)
        return list(all_visible)

    async def _post_one_batch(
        self, user_jwt: str, resource_type: str, ids: list[str]
    ) -> list[str]:
        """POST one batch to /api/v1/visibility/filter with retry.

        Raises:
            VisibilityFilterAuthError: 401/403 (no retry).
            VisibilityFilterProtocolError: 400/404/405/422/409 (no retry).
            VisibilityFilterUnavailableError: 5xx / network / timeout after retries.
        """
        assert self._client is not None  # invariant: caller already checked
        last_exc: Exception = VisibilityFilterUnavailableError("no attempts made")

        for attempt in range(self.retry_attempts + 1):
            try:
                response = await self._client.post(
                    "/api/v1/visibility/filter",
                    json={"resource_type": resource_type, "ids": ids},
                    headers={"Authorization": f"Bearer {user_jwt}"},
                )
                if response.status_code in (401, 403):
                    raise VisibilityFilterAuthError(f"status {response.status_code}")
                if response.status_code in (400, 404, 405, 409, 422):
                    raise VisibilityFilterProtocolError(
                        f"status {response.status_code}: {response.text[:200]}"
                    )
                if response.status_code in (408, 429) or response.status_code >= 500:
                    last_exc = VisibilityFilterUnavailableError(f"status {response.status_code}")
                    if attempt < self.retry_attempts:
                        await asyncio.sleep(2.0**attempt)  # 1 s, 2 s
                        continue
                    raise last_exc
                if response.status_code != 200:
                    raise VisibilityFilterProtocolError(
                        f"unexpected status {response.status_code}"
                    )
                try:
                    data = response.json()
                    parsed = _FilterResponse.model_validate(data)
                except Exception as parse_exc:
                    raise VisibilityFilterProtocolError(
                        f"malformed response: {parse_exc}"
                    ) from parse_exc
                return parsed.visible_ids

            except (VisibilityFilterAuthError, VisibilityFilterProtocolError):
                raise  # no retry on auth / protocol errors

            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = VisibilityFilterUnavailableError(f"network: {exc}")
                if attempt < self.retry_attempts:
                    await asyncio.sleep(2.0**attempt)
                    continue
                raise last_exc from exc

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
        is the entity's own ``entity_id``.
        For child entity types (comment, issue_history, sbom, dependency,
        quality_gate, gate, event), the parent_id comes from ``parent_entity_id``
        field added by T1's metadata builder extension.
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
