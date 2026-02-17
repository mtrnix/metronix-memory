"""MCP adapter — converts MCP tool results into Documents for ingestion.

GenericMCPAdapter handles any MCP server by calling read-like tools
and converting text results into Document objects. Per-server overrides
can customize tool selection and result parsing.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import structlog

from metatron.core.models import Document
from metatron.mcp.client import MCPClient
from metatron.mcp.config import MCPServerConfig

logger = structlog.get_logger()

# Keywords that indicate a tool is read-only (safe for data ingestion)
_READ_KEYWORDS = frozenset({
    "read", "get", "list", "search", "fetch", "query", "find", "browse",
    "show", "view", "describe", "export", "download", "retrieve",
})

# Keywords that indicate a tool mutates state (skip for ingestion)
_WRITE_KEYWORDS = frozenset({
    "write", "create", "update", "delete", "remove", "set", "put", "post",
    "modify", "add", "insert", "drop", "push", "send", "execute", "run",
})


def classify_tool(name: str, description: str) -> str:
    """Classify a tool as 'read' or 'write' based on name/description.

    Args:
        name: Tool name.
        description: Tool description.

    Returns:
        "read" or "write".
    """
    combined = f"{name} {description}".lower()
    for kw in _WRITE_KEYWORDS:
        if kw in combined:
            return "write"
    for kw in _READ_KEYWORDS:
        if kw in combined:
            return "read"
    return "read"  # default: treat as safe


def select_read_tools(
    tools: list[dict[str, Any]],
    explicit_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter tools to only those safe for reading/ingestion.

    Args:
        tools: Full tool list from MCP server.
        explicit_tools: If provided, only include these tool names.

    Returns:
        Filtered list of read-safe tools.
    """
    if explicit_tools:
        return [t for t in tools if t["name"] in explicit_tools]

    return [
        t for t in tools
        if classify_tool(t["name"], t.get("description", "")) == "read"
    ]


class GenericMCPAdapter:
    """Converts MCP tool results into Documents for the ingestion pipeline.

    Works with any MCP server by:
    1. Connecting to the server
    2. Listing available tools
    3. Calling read-safe tools
    4. Converting text results into Document objects
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config

    async def fetch_documents(
        self,
        workspace_id: str,
        tool_filter: list[str] | None = None,
    ) -> list[Document]:
        """Connect to MCP server and fetch documents via read tools.

        Args:
            workspace_id: Target workspace for documents.
            tool_filter: Specific tools to call. If None, auto-detect read tools.

        Returns:
            List of Documents ready for ingestion.
        """
        explicit_tools = tool_filter or self.config.read_tools or None
        documents: list[Document] = []

        async with MCPClient(self.config) as client:
            all_tools = await client.list_tools()
            read_tools = select_read_tools(all_tools, explicit_tools)

            if not read_tools:
                logger.warning(
                    "mcp.adapter.no_read_tools",
                    server=self.config.name,
                    total_tools=len(all_tools),
                )
                return documents

            logger.info(
                "mcp.adapter.fetching",
                server=self.config.name,
                read_tools=[t["name"] for t in read_tools],
            )

            for tool in read_tools:
                try:
                    results = await client.call_tool(tool["name"])
                    docs = self._results_to_documents(
                        results, tool["name"], workspace_id,
                    )
                    documents.extend(docs)
                except Exception as e:
                    logger.warning(
                        "mcp.adapter.tool_error",
                        server=self.config.name,
                        tool=tool["name"],
                        error=str(e),
                    )

        logger.info(
            "mcp.adapter.done",
            server=self.config.name,
            documents=len(documents),
        )
        return documents

    def _results_to_documents(
        self,
        content_blocks: list[dict[str, Any]],
        tool_name: str,
        workspace_id: str,
    ) -> list[Document]:
        """Convert MCP content blocks into Document objects.

        Each text block becomes one Document. Source ID is a hash of
        server name + tool name + content for deduplication.
        """
        documents: list[Document] = []

        for block in content_blocks:
            text = block.get("text", "")
            if not text or not text.strip():
                continue

            content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
            source_id = f"mcp:{self.config.name}:{tool_name}:{content_hash}"

            doc = Document(
                source_type="mcp",
                source_id=source_id,
                workspace_id=workspace_id,
                title=f"{self.config.name}/{tool_name}",
                content=text,
                author="mcp",
                metadata={
                    "mcp_server": self.config.name,
                    "mcp_tool": tool_name,
                    "type": "mcp",
                },
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            documents.append(doc)

        return documents


# ---------------------------------------------------------------------------
# Per-server adapter overrides
# ---------------------------------------------------------------------------

_ADAPTER_REGISTRY: dict[str, type[GenericMCPAdapter]] = {}


def register_adapter(server_pattern: str, adapter_cls: type[GenericMCPAdapter]) -> None:
    """Register a custom adapter for servers matching a name pattern.

    Args:
        server_pattern: Server name prefix (e.g., "github" matches "github-mcp").
        adapter_cls: Custom adapter class.
    """
    _ADAPTER_REGISTRY[server_pattern] = adapter_cls
    logger.info("mcp.adapter.registered", pattern=server_pattern)


def get_adapter(config: MCPServerConfig) -> GenericMCPAdapter:
    """Get the best adapter for a server config.

    Checks registered overrides first (prefix match), falls back to generic.

    Args:
        config: Server configuration.

    Returns:
        Adapter instance.
    """
    for pattern, cls in _ADAPTER_REGISTRY.items():
        if config.name.startswith(pattern):
            return cls(config)
    return GenericMCPAdapter(config)
