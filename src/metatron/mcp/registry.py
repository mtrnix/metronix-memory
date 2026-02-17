"""MCP server registry — file-based persistence for server configs.

Follows the same pattern as SyncState and AliasRegistry:
JSON file in .metatron/ directory, loaded on first access.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from metatron.mcp.config import MCPServerConfig

logger = structlog.get_logger()


class MCPServerRegistry:
    """Manages MCP server configurations with file-based persistence.

    Stores configs as a JSON array in .metatron/mcp_servers.json.
    Thread-safe for reads; writes happen on add/remove.
    """

    def __init__(self, state_dir: str = ".metatron") -> None:
        self._state_file = Path(state_dir) / "mcp_servers.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._servers: dict[str, MCPServerConfig] = {}
        self._load()

    def _load(self) -> None:
        """Load server configs from disk."""
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
            for item in data:
                config = MCPServerConfig(**item)
                self._servers[config.name] = config
            logger.info("mcp.registry.loaded", count=len(self._servers))
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning("mcp.registry.load_error", error=str(e))

    def _save(self) -> None:
        """Persist server configs to disk."""
        data = [cfg.model_dump() for cfg in self._servers.values()]
        self._state_file.write_text(json.dumps(data, indent=2))

    def add(self, config: MCPServerConfig) -> None:
        """Add or update an MCP server configuration.

        Args:
            config: Server configuration to store.
        """
        self._servers[config.name] = config
        self._save()
        logger.info("mcp.registry.added", name=config.name)

    def remove(self, name: str) -> bool:
        """Remove an MCP server configuration.

        Args:
            name: Server name to remove.

        Returns:
            True if removed, False if not found.
        """
        if name not in self._servers:
            return False
        del self._servers[name]
        self._save()
        logger.info("mcp.registry.removed", name=name)
        return True

    def get(self, name: str) -> MCPServerConfig | None:
        """Get a server config by name."""
        return self._servers.get(name)

    def list_servers(self, workspace_id: str | None = None) -> list[MCPServerConfig]:
        """List all server configs, optionally filtered by workspace.

        Args:
            workspace_id: If set, only return servers for this workspace.

        Returns:
            List of matching server configs.
        """
        servers = list(self._servers.values())
        if workspace_id:
            servers = [s for s in servers if not s.workspace_id or s.workspace_id == workspace_id]
        return servers

    def list_enabled(self, workspace_id: str | None = None) -> list[MCPServerConfig]:
        """List only enabled server configs."""
        return [s for s in self.list_servers(workspace_id) if s.enabled]
