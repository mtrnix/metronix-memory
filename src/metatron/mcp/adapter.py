"""MCP adapter — converts MCP tool results into Documents for ingestion.

GenericMCPAdapter uses a two-phase strategy:
  Phase 1 — discover items (list directories, then list files)
  Phase 2 — read each item (read_text_file / read_file with path)

Per-server overrides can customize tool selection and result parsing.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import structlog

from metatron.core.models import Document
from metatron.mcp.client import MCPClient
from metatron.mcp.config import MCPServerConfig

logger = structlog.get_logger()

# Keywords that indicate a tool is read-only (safe for data ingestion)
_READ_KEYWORDS = frozenset(
    {
        "read",
        "get",
        "list",
        "search",
        "fetch",
        "query",
        "find",
        "browse",
        "show",
        "view",
        "describe",
        "export",
        "download",
        "retrieve",
    }
)

# Keywords that indicate a tool mutates state (skip for ingestion)
_WRITE_KEYWORDS = frozenset(
    {
        "write",
        "create",
        "update",
        "delete",
        "remove",
        "set",
        "put",
        "post",
        "modify",
        "add",
        "insert",
        "drop",
        "push",
        "send",
        "execute",
        "run",
    }
)

# File extensions we treat as text content worth ingesting
_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".rst",
        ".py",
        ".js",
        ".ts",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".xml",
        ".html",
        ".css",
        ".sql",
        ".sh",
        ".bash",
        ".rb",
        ".php",
        ".kt",
        ".scala",
        ".r",
        ".csv",
        ".log",
        ".env",
    }
)


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

    return [t for t in tools if classify_tool(t["name"], t.get("description", "")) == "read"]


def _extract_text(result: Any) -> str:
    """Extract text from MCP tool result.

    Handles both raw list[dict] (from MCPClient.call_tool) and SDK
    objects with a .content attribute.
    """
    items: list[Any] = result if isinstance(result, list) else getattr(result, "content", [])
    texts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            t = item.get("text", "")
            if t:
                texts.append(t)
        elif hasattr(item, "text"):
            t = item.text
            if t:
                texts.append(t)
    return "\n".join(texts)


def _is_text_file(path: str) -> bool:
    """Check if a path looks like a text file we should ingest."""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _TEXT_EXTENSIONS)


# ---------------------------------------------------------------------------
# Tool discovery helpers
# ---------------------------------------------------------------------------

# Preferred names for the "list" tool (ordered by priority)
_LIST_TOOL_NAMES = [
    "list_directory",
    "list_dir",
    "list_files",
    "ls",
    "list_allowed_directories",
]

# Preferred names for the "get" / read tool (ordered by priority)
_GET_TOOL_NAMES = [
    "read_text_file",
    "read_file",
    "get_file",
    "get_text_file",
    "read_file_content",
    "get_file_content",
]

# Fallback: use search_files if no list tool found
_SEARCH_TOOL_NAMES = ["search_files", "search", "find_files"]


def _find_tool_by_names(
    tools: list[dict[str, Any]],
    candidates: list[str],
) -> dict[str, Any] | None:
    """Find first tool whose name matches one of the candidate names."""
    tool_map = {t["name"]: t for t in tools}
    for name in candidates:
        if name in tool_map:
            return tool_map[name]
    return None


class GenericMCPAdapter:
    """Converts MCP tool results into Documents for the ingestion pipeline.

    Two-phase approach:
    1. Discover items — list directories, then list files in each
    2. Read items — read each discovered file via read_text_file/read_file
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config

    async def fetch_documents(
        self,
        workspace_id: str,
        tool_filter: list[str] | None = None,
    ) -> list[Document]:
        """Connect to MCP server and fetch documents via two-phase read.

        Args:
            workspace_id: Target workspace for documents.
            tool_filter: Specific tools to call. If None, auto-detect.

        Returns:
            List of Documents ready for ingestion.
        """
        documents: list[Document] = []

        async with MCPClient(self.config) as client:
            all_tools = await client.list_tools()

            # Resolve the "get" tool (for reading individual files)
            get_tool = self._find_get_tool(all_tools)
            if not get_tool:
                logger.warning(
                    "mcp.adapter.no_get_tool",
                    server=self.config.name,
                    tools=[t["name"] for t in all_tools],
                )
                return documents

            # Phase 1: discover file paths
            paths = await self._discover_items(client, all_tools)

            if not paths:
                logger.info(
                    "mcp.adapter.no_items",
                    server=self.config.name,
                )
                return documents

            logger.info(
                "mcp.adapter.discovered",
                server=self.config.name,
                items=len(paths),
            )

            # Phase 2: read each file
            for path in paths:
                doc = await self._read_item(
                    client,
                    get_tool["name"],
                    path,
                    workspace_id,
                )
                if doc:
                    documents.append(doc)

        logger.info(
            "mcp.adapter.done",
            server=self.config.name,
            documents=len(documents),
        )
        return documents

    async def _discover_items(
        self,
        client: MCPClient,
        all_tools: list[dict[str, Any]],
    ) -> list[str]:
        """Phase 1: discover file paths to read.

        Strategy (tried in order):
        1. config.list_tool override
        2. list_allowed_directories + list_directory (per root)
        3. list_directory with "/"
        4. search_files("*") fallback
        """
        tool_map = {t["name"]: t for t in all_tools}

        # Honour explicit config override
        if self.config.list_tool and self.config.list_tool in tool_map:
            lt = tool_map[self.config.list_tool]
            if "allowed" in lt["name"] or "root" in lt["name"]:
                return await self._discover_via_roots(client, lt, all_tools)
            return await self._list_directory(client, lt["name"], "/")

        # Strategy 1: list_allowed_directories → list_directory per root
        roots_tool = tool_map.get("list_allowed_directories")
        dir_tool = tool_map.get("list_directory")
        if roots_tool and dir_tool:
            paths = await self._discover_via_roots(
                client,
                roots_tool,
                all_tools,
            )
            if paths:
                return paths

        # Strategy 2: list_directory with "/"
        if dir_tool:
            return await self._list_directory(client, dir_tool["name"], "/")

        # Strategy 3: any other list-like tool
        list_tool = _find_tool_by_names(all_tools, _LIST_TOOL_NAMES)
        if list_tool:
            return await self._list_directory(client, list_tool["name"], "/")

        # Strategy 4: search_files fallback
        search_tool = _find_tool_by_names(all_tools, _SEARCH_TOOL_NAMES)
        if search_tool:
            return await self._discover_via_search(client, search_tool)

        return []

    async def _discover_via_roots(
        self,
        client: MCPClient,
        roots_tool: dict[str, Any],
        all_tools: list[dict[str, Any]],
    ) -> list[str]:
        """Get root directories, then list files in each."""
        try:
            result = await client.call_tool(roots_tool["name"])
        except Exception as e:
            logger.warning(
                "mcp.adapter.roots_error",
                tool=roots_tool["name"],
                error=str(e),
            )
            return []

        dirs = self._parse_directories(_extract_text(result))

        # Find a directory listing tool (not the roots tool)
        dir_tool = _find_tool_by_names(
            [t for t in all_tools if t["name"] != roots_tool["name"]],
            _LIST_TOOL_NAMES,
        )
        if not dir_tool:
            # Roots themselves might be files
            return [d for d in dirs if _is_text_file(d)]

        all_paths: list[str] = []
        for directory in dirs:
            paths = await self._list_directory(
                client,
                dir_tool["name"],
                directory,
            )
            all_paths.extend(paths)

        return all_paths

    async def _list_directory(
        self,
        client: MCPClient,
        tool_name: str,
        directory: str,
    ) -> list[str]:
        """Call list_directory tool and parse file paths."""
        try:
            result = await client.call_tool(tool_name, {"path": directory})
        except Exception as e:
            logger.warning(
                "mcp.adapter.list_error",
                tool=tool_name,
                directory=directory,
                error=str(e),
            )
            return []

        return self._parse_directory_listing(_extract_text(result), directory)

    async def _discover_via_search(
        self,
        client: MCPClient,
        search_tool: dict[str, Any],
    ) -> list[str]:
        """Fallback: use search_files to discover items."""
        try:
            result = await client.call_tool(
                search_tool["name"],
                {"pattern": "*", "query": ""},
            )
        except Exception as e:
            logger.warning(
                "mcp.adapter.search_error",
                tool=search_tool["name"],
                error=str(e),
            )
            return []

        text = _extract_text(result)
        paths = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and _is_text_file(line.strip())
        ]
        return paths

    async def _read_item(
        self,
        client: MCPClient,
        get_tool_name: str,
        path: str,
        workspace_id: str,
    ) -> Document | None:
        """Phase 2: read a single file and convert to Document."""
        try:
            result = await client.call_tool(
                get_tool_name,
                {"path": path},
            )
        except Exception as e:
            logger.warning(
                "mcp.adapter.read_error",
                tool=get_tool_name,
                path=path,
                error=str(e),
            )
            return None

        text = _extract_text(result)
        if not text.strip():
            return None

        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        source_id = f"mcp:{self.config.name}:{path}:{content_hash}"

        return Document(
            source_type="mcp",
            source_id=source_id,
            workspace_id=workspace_id,
            title=f"{self.config.name}:{path}",
            content=text,
            author="mcp",
            metadata={
                "mcp_server": self.config.name,
                "mcp_tool": get_tool_name,
                "path": path,
                "type": "mcp",
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def _find_get_tool(
        self,
        all_tools: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Find the best "read single file" tool.

        Priority: config.get_tool → read_text_file → read_file → etc.
        """
        if self.config.get_tool:
            tool_map = {t["name"]: t for t in all_tools}
            if self.config.get_tool in tool_map:
                return tool_map[self.config.get_tool]

        return _find_tool_by_names(all_tools, _GET_TOOL_NAMES)

    @staticmethod
    def _parse_directories(text: str) -> list[str]:
        """Parse root directories from tool output.

        Handles JSON arrays, "Allowed directories:" prefix, [DIR] tags,
        and plain path lines.  Only lines starting with ``/`` (after
        stripping tags) are treated as directory paths.
        """
        text = text.strip()
        if not text:
            return []

        # Try JSON array
        if text.startswith("["):
            try:
                import json

                items = json.loads(text)
                if isinstance(items, list):
                    return [str(i).strip() for i in items if str(i).strip()]
            except (json.JSONDecodeError, ValueError):
                pass

        # Line-by-line — only keep actual paths (start with /)
        dirs: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip common prefixes like "[DIR]", "- ", "* "
            cleaned = re.sub(r"^\[DIR\]\s*", "", line)
            cleaned = re.sub(r"^[-*]\s+", "", cleaned)
            cleaned = cleaned.strip()
            # Only accept absolute paths — skip labels like "Allowed directories:"
            if cleaned.startswith("/"):
                dirs.append(cleaned)
        return dirs

    @staticmethod
    def _parse_directory_listing(text: str, parent_dir: str = "") -> list[str]:
        """Parse file paths from a directory listing.

        Relative filenames are prefixed with *parent_dir* so that callers
        get absolute paths suitable for ``read_text_file(path=...)``.

        Handles formats like:
          [FILE] bug-report.md
          [DIR] subdir/
          - file.txt
          /absolute/path/file.md
        """
        text = text.strip()
        if not text:
            return []

        # Normalise parent: ensure trailing slash for joining
        base = parent_dir.rstrip("/") + "/" if parent_dir else ""

        def _full_path(p: str) -> str:
            """Return absolute path, prepending parent_dir if relative."""
            if p.startswith("/"):
                return p
            return f"{base}{p}"

        # Try JSON array
        if text.startswith("["):
            try:
                import json

                items = json.loads(text)
                if isinstance(items, list):
                    paths = [str(i).strip() for i in items if str(i).strip()]
                    return [_full_path(p) for p in paths if _is_text_file(p)]
            except (json.JSONDecodeError, ValueError):
                pass

        files: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Skip directory entries
            if line.startswith("[DIR]") or line.endswith("/"):
                continue

            # Strip [FILE] prefix
            cleaned = re.sub(r"^\[FILE\]\s*", "", line)
            # Strip list markers
            cleaned = re.sub(r"^[-*]\s+", "", cleaned)

            if cleaned and _is_text_file(cleaned):
                files.append(_full_path(cleaned))

        return files

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
