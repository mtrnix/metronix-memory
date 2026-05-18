"""ASOC connector — pulls security data from ASOC via REST API.

Fetches 10 entity types in a deterministic order:
    project, layer, issue, comment, issue_history,
    scan_result, sbom, dependency, quality_gate, event.

Supports:
- Bootstrap (full fetch, since=None).
- Incremental sync via ``updated_after`` query param.
- Automatic fallback to client-side filtering when ``updated_after`` is
  unsupported by a specific endpoint (flags per entity type).
- Resume hints (``after_resource`` / ``after_id``) for crash-safe bootstrap
  recovery.
- Exponential backoff with Retry-After header honoring for 429 responses.

ASOC API notes:
    Endpoint paths in ``_ENDPOINTS`` are best-guess from the Confluence spec.
    Verify against the ASOC dev instance during integration testing and adjust
    if paths differ — connector logic is endpoint-agnostic; only this dict and
    ``asoc_processing`` need to change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from metatron.core.exceptions import ConnectorError, RateLimitError
from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal sentinel
# ---------------------------------------------------------------------------


class _UpdatedAfterUnsupportedError(Exception):  # noqa: N818
    """Internal sentinel: 400 response indicates updated_after is not supported."""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class AsocConnector(ConnectorInterface):
    """Pulls ASOC security entities and turns them into indexable Documents.

    Config keys (``decrypted_config``):
        url: ASOC base URL (e.g. ``https://asoc.example.com``)
        service_token: Bearer API token (``X-API-Token`` header)
        project_id: UUID of the ASOC project to sync
        asoc_instance_id: Instance identifier used to construct workspace IDs
    """

    source_role: str = "security_scanner"

    ENTITY_ORDER: tuple[str, ...] = (
        "project",
        "layer",
        "issue",
        "comment",
        "issue_history",
        "scan_result",
        "sbom",
        "dependency",
        "quality_gate",
        "event",
    )

    # Best-guess endpoint paths from Confluence spec (page 33783809).
    # Adjust if ASOC dev instance returns 404 — only this dict needs changing.
    _ENDPOINTS: dict[str, str] = {
        "project": "/api/v1/projects/{project_id}",
        "layer": "/api/v1/projects/{project_id}/layers",
        "issue": "/api/v1/projects/{project_id}/issues",
        "comment": "/api/v1/projects/{project_id}/issues/{issue_id}/comments",
        "issue_history": "/api/v1/projects/{project_id}/issues/{issue_id}/history",
        "scan_result": "/api/v1/projects/{project_id}/scans",
        "sbom": "/api/v1/projects/{project_id}/sboms",
        "dependency": "/api/v1/projects/{project_id}/dependencies",
        "quality_gate": "/api/v1/projects/{project_id}/quality-gates",
        "event": "/api/v1/projects/{project_id}/events",
    }

    _PAGE_SIZE: int = 50
    _RETRY_ATTEMPTS: int = 3
    _BACKOFF_BASE: float = 1.0  # seconds

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._config: dict[str, str] = {}
        self._base_url: str = ""
        self._project_id: str = ""
        self._instance_id: str = ""
        # Track which entity types support updated_after; flip to False on 400.
        self._updated_after_supported: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # ConnectorInterface
    # ------------------------------------------------------------------

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Validate config and create the persistent httpx client.

        Raises:
            ConnectorError: If any required key is missing or empty.
        """
        for key in ("url", "service_token", "project_id", "asoc_instance_id"):
            if not decrypted_config.get(key):
                raise ConnectorError(f"asoc.configure.missing_key: {key}")

        self._config = decrypted_config
        self._base_url = decrypted_config["url"].rstrip("/")
        self._project_id = decrypted_config["project_id"]
        self._instance_id = decrypted_config["asoc_instance_id"]
        self._updated_after_supported = {e: True for e in self.ENTITY_ORDER}

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-API-Token": decrypted_config["service_token"],
                "Accept": "application/json",
                "User-Agent": "metatron-asoc-connector/1.0",
            },
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=False,
        )
        logger.info(
            "asoc.configured",
            base_url=self._base_url,
            project_id=self._project_id,
            connection_id=connection.id,
        )

    async def fetch(
        self,
        workspace_id: str,
        since: datetime | None = None,
        *,
        after_resource: str | None = None,
        after_id: str | None = None,
    ) -> list[Document]:
        """Fetch all ASOC entities and return them as Documents.

        Args:
            workspace_id: Target Metatron workspace.
            since: Only return entities updated after this timestamp (incremental).
            after_resource: Entity type name to resume from (inclusive).
            after_id: Entity ID to resume from within *after_resource* (exclusive —
                resume AFTER this id).

        Returns:
            Flat list of Documents in ENTITY_ORDER order.
        """
        if self._client is None:
            raise ConnectorError("asoc.fetch: connector not configured — call configure() first")

        # Resolve resume position.
        start_idx = 0
        if after_resource is not None:
            if after_resource in self.ENTITY_ORDER:
                start_idx = self.ENTITY_ORDER.index(after_resource)
            else:
                logger.warning(
                    "asoc.fetch.invalid_resume_resource",
                    value=after_resource,
                    valid=list(self.ENTITY_ORDER),
                )
                after_id = None  # ignore stale id too

        documents: list[Document] = []
        for i, entity_type in enumerate(self.ENTITY_ORDER):
            if i < start_idx:
                continue
            skip_until_id = after_id if (i == start_idx and after_id) else None
            async for raw in self._fetch_entity_type(entity_type, since, skip_until_id):
                doc = self._entity_to_document(entity_type, raw, workspace_id)
                if doc is not None:
                    documents.append(doc)

        logger.info(
            "asoc.fetch.done",
            workspace_id=workspace_id,
            total=len(documents),
            since=since,
        )
        return documents

    async def health_check(self) -> bool:
        """Probe the project endpoint. Returns True if the API is reachable."""
        if self._client is None:
            return False
        try:
            path = self._ENDPOINTS["project"].format(project_id=self._project_id)
            response = await self._request("GET", path)
            return response.status_code < 300
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Entity iteration helpers
    # ------------------------------------------------------------------

    async def _fetch_entity_type(
        self,
        entity_type: str,
        since: datetime | None,
        start_after_id: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw entity dicts for *entity_type*.

        Comment and issue_history require per-issue fan-out; all others use
        direct project-level pagination.
        """
        if entity_type in ("comment", "issue_history"):
            async for raw in self._fetch_per_issue_entities(entity_type, since, start_after_id):
                yield raw
            return

        path_template = self._ENDPOINTS[entity_type]
        path = path_template.format(project_id=self._project_id)

        params: dict[str, str] = {}
        if since is not None and self._updated_after_supported[entity_type]:
            params["updated_after"] = since.isoformat()

        skipping = start_after_id is not None
        try:
            async for raw in self._get_paginated(path, params):
                if skipping:
                    if str(raw.get("id")) == start_after_id:
                        skipping = False  # resume from NEXT item
                    continue
                if since is not None and not self._updated_after_supported[entity_type]:
                    # Client-side filter when server doesn't support updated_after.
                    item_updated = _parse_updated_at(raw, entity_type)
                    if item_updated is not None and item_updated <= since:
                        continue
                yield raw

        except _UpdatedAfterUnsupportedError:
            # Endpoint doesn't support updated_after — fall back to client-side filter.
            self._updated_after_supported[entity_type] = False
            logger.info("asoc.updated_after.unsupported", entity_type=entity_type)
            params.pop("updated_after", None)
            skipping = start_after_id is not None
            async for raw in self._get_paginated(path, params):
                if skipping:
                    if str(raw.get("id")) == start_after_id:
                        skipping = False
                    continue
                if since is not None:
                    item_updated = _parse_updated_at(raw, entity_type)
                    if item_updated is not None and item_updated <= since:
                        continue
                yield raw

    async def _fetch_per_issue_entities(
        self,
        entity_type: str,
        since: datetime | None,
        start_after_id: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Fan out to per-issue endpoints for ``comment`` and ``issue_history``.

        Fetches the issue list fresh each run; acceptable inefficiency for MVP.
        ``start_after_id`` applies across the flattened stream.
        """
        issue_path = self._ENDPOINTS["issue"].format(project_id=self._project_id)
        skipping = start_after_id is not None
        async for issue in self._get_paginated(issue_path, {}):
            issue_id = str(issue.get("id", ""))
            if not issue_id:
                continue
            sub_path_template = self._ENDPOINTS[entity_type]
            sub_path = sub_path_template.format(
                project_id=self._project_id, issue_id=issue_id
            )
            issue_view_id = issue.get("view_id")
            try:
                async for raw in self._get_paginated(sub_path, {}):
                    # Inject parent issue identifiers so processing can build URLs.
                    raw = {**raw, "issue_id": issue_id, "issue_view_id": issue_view_id}
                    if skipping:
                        if str(raw.get("id")) == start_after_id:
                            skipping = False
                        continue
                    if since is not None:
                        item_updated = _parse_updated_at(raw, entity_type)
                        if item_updated is not None and item_updated <= since:
                            continue
                    yield raw
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    # Issue has no comments/history — skip silently.
                    logger.debug(
                        "asoc.per_issue.404",
                        entity_type=entity_type,
                        issue_id=issue_id,
                    )
                else:
                    logger.warning(
                        "asoc.per_issue.error",
                        entity_type=entity_type,
                        issue_id=issue_id,
                        status=exc.response.status_code,
                    )

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    async def _get_paginated(
        self, path: str, params: dict[str, str]
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate a list endpoint, yielding individual raw items.

        Raises:
            _UpdatedAfterUnsupported: When the response is 400 and mentions
                ``updated_after`` in the body.
            httpx.HTTPStatusError: For other 4xx/5xx responses.
        """
        page = 1
        page_size = self._PAGE_SIZE
        while True:
            page_params = {**params, "page": str(page), "page_size": str(page_size)}
            response = await self._request("GET", path, params=page_params)

            if response.status_code == 400 and "updated_after" in response.text:
                raise _UpdatedAfterUnsupportedError()
            response.raise_for_status()

            data = response.json()
            # Cope with multiple common response envelope shapes.
            if isinstance(data, list):
                items: list[dict[str, Any]] = data
            else:
                items = (
                    data.get("items")
                    or data.get("data")
                    or data.get("results")
                    or []
                )

            for item in items:
                yield item

            # Detect end of pagination.
            if not items:
                return
            if len(items) < page_size:
                return
            if data.get("has_next") is False:
                return
            page += 1

    # ------------------------------------------------------------------
    # HTTP with retry / backoff
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request with retry and exponential backoff.

        Retry policy:
        - Network errors / 5xx → retry up to _RETRY_ATTEMPTS with 1s/2s/4s backoff.
        - 429 Too Many Requests → honor ``Retry-After`` header (default 60 s), max 3 retries.
        - 401 / 403 → raise ConnectorError immediately (no retry).
        - Other 4xx → return the response as-is (caller handles e.g. 400 for pagination check,
          404 for missing sub-resources).
        """
        assert self._client is not None, "configure() must be called before _request()"

        last_exc: Exception | None = None
        for attempt in range(self._RETRY_ATTEMPTS):
            try:
                response = await self._client.request(method, path, **kwargs)

                if response.status_code in (401, 403):
                    raise ConnectorError(
                        f"asoc.auth_error: {response.status_code} {response.text[:200]}"
                    )

                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("Retry-After", "60")
                    )
                    if attempt >= self._RETRY_ATTEMPTS - 1:
                        raise RateLimitError(
                            f"asoc.rate_limit: 429 after {attempt + 1} attempts",
                            retry_after=retry_after,
                        )
                    logger.warning(
                        "asoc.rate_limit.backoff",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    # Treat 5xx as transient; retry with backoff.
                    delay = self._BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "asoc.server_error.retry",
                        status=response.status_code,
                        delay=delay,
                        attempt=attempt + 1,
                    )
                    last_exc = ConnectorError(
                        f"asoc.server_error: {response.status_code} {response.text[:200]}"
                    )
                    await asyncio.sleep(delay)
                    continue

                return response

            except ConnectorError:
                raise
            except RateLimitError:
                raise
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout) as exc:
                delay = self._BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "asoc.network_error.retry",
                    error=str(exc),
                    delay=delay,
                    attempt=attempt + 1,
                )
                last_exc = ConnectorError(f"asoc.network_error: {exc}")
                await asyncio.sleep(delay)
            except httpx.HTTPError as exc:
                last_exc = ConnectorError(f"asoc.http_error: {exc}")
                await asyncio.sleep(self._BACKOFF_BASE * (2**attempt))

        raise ConnectorError(
            f"asoc.request_failed after {self._RETRY_ATTEMPTS} attempts: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Document construction
    # ------------------------------------------------------------------

    def _entity_to_document(
        self,
        entity_type: str,
        raw: dict[str, Any],
        workspace_id: str,
    ) -> Document | None:
        """Convert a raw ASOC payload into a ``Document``.

        Returns ``None`` when the payload is malformed; the caller should skip it.
        """
        from metatron.connectors.asoc_processing import (
            build_asoc_url_hint,
            deterministic_document_id,
            entity_to_markdown,
            entity_to_metadata,
            process_asoc_entity,
        )

        try:
            structured = process_asoc_entity(entity_type, raw)
            content = entity_to_markdown(entity_type, structured)
            metadata = entity_to_metadata(entity_type, structured, self._project_id)
            url_hint = build_asoc_url_hint(entity_type, structured, metadata)
            metadata["asoc_url_hint"] = url_hint

            # Stringify all metadata values for the Document.metadata: dict[str, str] type.
            str_metadata: dict[str, str] = {
                k: str(v) if v is not None else "" for k, v in metadata.items()
            }

            return Document(
                id=deterministic_document_id(entity_type, structured["entity_id"], content),
                source_type="asoc",
                source_id=structured["entity_id"],
                workspace_id=workspace_id,
                title=structured.get("title", ""),
                content=content,
                url=f"{self._base_url}{url_hint}",
                author=structured.get("author", ""),
                source_role="security_scanner",
                metadata=str_metadata,
                created_at=structured.get("created_at") or datetime.utcnow(),
                updated_at=structured.get("updated_at") or datetime.utcnow(),
            )
        except Exception as exc:
            logger.warning(
                "asoc.entity.malformed",
                entity_type=entity_type,
                error=str(exc),
                raw_id=raw.get("id"),
            )
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_updated_at(raw: dict[str, Any], entity_type: str) -> datetime | None:
    """Extract and parse the ``updated_at`` (or ``created_at``) field from a raw entity dict."""
    from metatron.connectors.asoc_processing import _parse_dt

    value = raw.get("updated_at") or raw.get("created_at")
    return _parse_dt(value)
