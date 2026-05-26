"""ASOC connector — pulls security data from ASOC via admin-mode MCP tool calls.

Fetches 10 entity types in a deterministic order:
    project, layer, issue, comment, issue_history,
    scan_result, sbom, dependency, gate, event.

Supports:
- Bootstrap (full fetch, since=None).
- Incremental sync via ``updated_after`` argument to MCP list tools.
- Resume hints (``after_resource`` / ``after_id``) for crash-safe bootstrap
  recovery.
- Retry-with-backoff delegated to ``AsocMcpClient._call_with_retry``.

Transport:
    Uses ``AsocMcpClient`` in admin mode (``X-Api-Token`` only, no session).
    Admin mode acts as the predefined ASOC system user ``metatron`` (role
    ``isadm``) — per ASOC_API_CONTRACT.md §3.2.

MCP tool mapping:
    project       → asoc_list_projects  (project-level, single result list)
    layer         → asoc_list_layers
    issue         → asoc_list_issues
    comment       → asoc_get_issue_comments  (per-issue fan-out)
    issue_history → asoc_get_issue_history   (per-issue fan-out)
    scan_result   → asoc_list_scan_results
    sbom          → asoc_list_sboms
    dependency    → asoc_list_dependencies
    gate          → asoc_list_quality_gates
    event         → asoc_list_events

Pagination:
    MCP tools use ``cursor``/``next_cursor`` convention.  When a response
    includes a non-empty ``next_cursor``, the next call passes
    ``cursor=next_cursor``.  An absent or null ``next_cursor`` signals the last
    page.

URL hints:
    Each MCP entity item carries a ``url_hint`` field (ASOC plan §1.4).
    ``entity_to_document`` reads it directly from the raw item dict; no local
    URL-template logic.  Missing ``url_hint`` → ``Document.url`` is empty;
    a warning is logged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from metatron.core.exceptions import ConnectorError
from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from metatron.integrations.asoc_mcp_client import AsocMcpClient

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# MCP tool names for each entity type
# ---------------------------------------------------------------------------

_MCP_LIST_TOOLS: dict[str, str] = {
    "project": "asoc_list_projects",
    "layer": "asoc_list_layers",
    "issue": "asoc_list_issues",
    "scan_result": "asoc_list_scan_results",
    "sbom": "asoc_list_sboms",
    "dependency": "asoc_list_dependencies",
    # "gate" is the canonical entity_type per ASOC analytics docs (ASOC_API_CONTRACT.md)
    "gate": "asoc_list_quality_gates",
    "quality_gate": "asoc_list_quality_gates",  # backward-compat alias
    "event": "asoc_list_events",
}

# Per-issue fan-out tools — called with project_id + issue_id arguments.
_MCP_PER_ISSUE_TOOLS: dict[str, str] = {
    "comment": "asoc_get_issue_comments",
    "issue_history": "asoc_get_issue_history",
}

# Page size hint sent to MCP tools (honoured if the tool supports ``limit``).
_PAGE_SIZE: int = 50


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class AsocConnector(ConnectorInterface):
    """Pulls ASOC security entities via admin-mode MCP and converts to Documents.

    Config keys (``decrypted_config``):
        project_id: UUID of the ASOC project to sync.
        asoc_instance_id: Instance identifier used to construct workspace IDs.

    The ``mcp_client`` (admin mode) is injected via :meth:`set_mcp_client` or
    :meth:`configure`.  When built from the lifespan factory, the admin-mode
    ``AsocMcpClient`` is passed directly; no per-connector httpx client is kept.
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
        "gate",
        "event",
    )

    def __init__(self) -> None:
        self._mcp: AsocMcpClient | None = None
        self._project_id: str = ""
        self._instance_id: str = ""

    # ------------------------------------------------------------------
    # ConnectorInterface
    # ------------------------------------------------------------------

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Validate config and store project metadata.

        Required config keys:
            project_id: UUID of the ASOC project to sync.
            asoc_instance_id: Instance identifier.

        The MCP client is NOT constructed here — it is injected via
        :meth:`set_mcp_client` by the lifespan factory (admin-mode client is
        shared across all connectors and workspaces).

        Raises:
            ConnectorError: If any required key is missing or empty.
        """
        for key in ("project_id", "asoc_instance_id"):
            if not decrypted_config.get(key):
                raise ConnectorError(f"asoc.configure.missing_key: {key}")

        self._project_id = decrypted_config["project_id"]
        self._instance_id = decrypted_config["asoc_instance_id"]
        logger.info(
            "asoc.configured",
            project_id=self._project_id,
            connection_id=connection.id,
        )

    def set_mcp_client(self, mcp_client: AsocMcpClient) -> None:
        """Inject the admin-mode MCP client (called by the lifespan factory)."""
        self._mcp = mcp_client

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

        Raises:
            ConnectorError: If :meth:`configure` or :meth:`set_mcp_client` has not
                been called, or if an MCP call fails after all retries.
        """
        if self._mcp is None:
            raise ConnectorError(
                "asoc.fetch: connector not configured — call configure() and "
                "set_mcp_client() before fetch()"
            )

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
        """Return True if the MCP client is configured, False otherwise."""
        return self._mcp is not None

    # ------------------------------------------------------------------
    # Entity iteration helpers
    # ------------------------------------------------------------------

    async def _fetch_entity_type(
        self,
        entity_type: str,
        since: datetime | None,
        start_after_id: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw entity dicts for *entity_type* via MCP tool calls.

        Comment and issue_history require per-issue fan-out; all others use
        direct project-level pagination.
        """
        if entity_type in _MCP_PER_ISSUE_TOOLS:
            async for raw in self._fetch_per_issue_entities(entity_type, since, start_after_id):
                yield raw
            return

        tool_name = _MCP_LIST_TOOLS.get(entity_type)
        if tool_name is None:
            logger.warning("asoc.fetch.unknown_entity_type", entity_type=entity_type)
            return

        arguments: dict[str, Any] = {
            "project_id": self._project_id,
            "limit": _PAGE_SIZE,
        }
        if since is not None:
            arguments["updated_after"] = since.isoformat()

        skipping = start_after_id is not None
        async for raw in self._paginate_mcp(tool_name, arguments):
            if skipping:
                if str(raw.get("id")) == start_after_id:
                    skipping = False  # resume from NEXT item
                continue
            yield raw

    async def _fetch_per_issue_entities(
        self,
        entity_type: str,
        since: datetime | None,
        start_after_id: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Fan out to per-issue MCP tools for ``comment`` and ``issue_history``.

        Fetches the full issue list fresh each run; acceptable for MVP scale.
        ``start_after_id`` applies across the flattened stream.
        """
        tool_name = _MCP_PER_ISSUE_TOOLS[entity_type]
        skipping = start_after_id is not None

        # Fetch all issues first (no since filter on the issue scan — we need
        # all issue IDs for the fan-out).
        async for issue in self._paginate_mcp(
            "asoc_list_issues",
            {"project_id": self._project_id, "limit": _PAGE_SIZE},
        ):
            issue_id = str(issue.get("id", ""))
            if not issue_id:
                continue
            issue_view_id = issue.get("view_id")
            try:
                sub_args: dict[str, Any] = {
                    "project_id": self._project_id,
                    "issue_id": issue_id,
                    "limit": _PAGE_SIZE,
                }
                async for raw in self._paginate_mcp(tool_name, sub_args):
                    # Inject parent issue identifiers so processing can use them.
                    raw = {**raw, "issue_id": issue_id, "issue_view_id": issue_view_id}
                    if skipping:
                        if str(raw.get("id")) == start_after_id:
                            skipping = False
                        continue
                    if since is not None:
                        item_updated = _parse_updated_at(raw)
                        if item_updated is not None and item_updated <= since:
                            continue
                    yield raw
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "asoc.per_issue.error",
                    entity_type=entity_type,
                    issue_id=issue_id,
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # MCP pagination
    # ------------------------------------------------------------------

    async def _paginate_mcp(
        self,
        tool_name: str,
        base_arguments: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate an MCP list tool, yielding individual raw item dicts.

        Uses ``cursor`` / ``next_cursor`` convention.  An absent or ``null``
        ``next_cursor`` signals the last page.

        Raises:
            ConnectorError: On MCP authentication, unavailability, or protocol error.
        """
        from metatron.integrations.asoc_mcp_client import (
            McpAuthError,
            McpProtocolError,
            McpUnavailableError,
            ToolNotAllowedError,
        )

        assert self._mcp is not None  # invariant: checked in fetch()
        cursor: str | None = None

        while True:
            arguments = dict(base_arguments)
            if cursor is not None:
                arguments["cursor"] = cursor

            try:
                result = await self._mcp.invoke(
                    session_id="",  # admin mode — no user session
                    tool_name=tool_name,
                    arguments=arguments,
                )
            except McpAuthError as exc:
                raise ConnectorError(f"asoc.mcp.auth_error [{tool_name}]: {exc}") from exc
            except ToolNotAllowedError as exc:
                raise ConnectorError(f"asoc.mcp.tool_not_allowed [{tool_name}]: {exc}") from exc
            except McpUnavailableError as exc:
                raise ConnectorError(f"asoc.mcp.unavailable [{tool_name}]: {exc}") from exc
            except McpProtocolError as exc:
                raise ConnectorError(f"asoc.mcp.protocol_error [{tool_name}]: {exc}") from exc

            # Parse response content blocks.
            payload = _parse_mcp_content(result.content, tool_name)

            # Tolerate list response OR dict-with-items response.
            if isinstance(payload, list):
                items: list[dict[str, Any]] = payload
                next_cursor: str | None = None
            else:
                items = payload.get("items") or payload.get("data") or payload.get("results") or []
                next_cursor = payload.get("next_cursor") or None

            for item in items:
                if isinstance(item, dict):
                    yield item

            # End of pagination.
            if not items or not next_cursor:
                return
            cursor = next_cursor

    # ------------------------------------------------------------------
    # Document construction
    # ------------------------------------------------------------------

    def _entity_to_document(
        self,
        entity_type: str,
        raw: dict[str, Any],
        workspace_id: str,
    ) -> Document | None:
        """Convert a raw ASOC MCP payload into a ``Document``.

        Reads ``url_hint`` directly from the raw dict (provided by ASOC MCP
        per ASOC_API_CONTRACT.md §9 item 6).  If missing, logs a warning and
        leaves ``Document.url`` empty.

        Returns ``None`` when the payload is malformed; the caller should skip it.
        """
        from metatron.connectors.asoc_processing import (
            deterministic_document_id,
            entity_to_markdown,
            entity_to_metadata,
            process_asoc_entity,
        )

        try:
            structured = process_asoc_entity(entity_type, raw)
            content = entity_to_markdown(entity_type, structured)
            metadata = entity_to_metadata(entity_type, structured, self._project_id)

            # Read url_hint from the MCP response directly (no local templates).
            url_hint: str = raw.get("url_hint") or ""
            if not url_hint:
                logger.warning(
                    "asoc.entity.missing_url_hint",
                    entity_type=entity_type,
                    entity_id=structured.get("entity_id"),
                )
            metadata["asoc_url_hint"] = url_hint

            # Stringify all metadata values for Document.metadata: dict[str, str].
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
                url=url_hint,
                author=structured.get("author", ""),
                source_role="security_scanner",
                metadata=str_metadata,
                created_at=structured.get("created_at") or datetime.now(UTC),
                updated_at=structured.get("updated_at") or datetime.now(UTC),
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


def _parse_updated_at(raw: dict[str, Any]) -> datetime | None:
    """Extract and parse the ``updated_at`` (or ``created_at``) field from a raw entity dict."""
    from metatron.connectors.asoc_processing import _parse_dt

    value = raw.get("updated_at") or raw.get("created_at")
    return _parse_dt(value)


def _parse_mcp_content(content: list[dict[str, Any]], tool_name: str) -> Any:
    """Extract a parsed value from MCP content blocks.

    Handles two block shapes:
    - ``{"type": "json", "data": <value>}``
    - ``{"type": "text", "text": "<json string>"}``

    Returns the first parseable value found, or an empty dict on failure.
    """
    for block in content:
        if block.get("type") == "json":
            data = block.get("data")
            if data is not None:
                return data

        text = block.get("text", "")
        if isinstance(text, str) and text.strip():
            try:
                return json.loads(text)
            except Exception:
                continue

    logger.warning(
        "asoc.mcp.unparseable_response",
        tool_name=tool_name,
        block_count=len(content),
    )
    return {}
