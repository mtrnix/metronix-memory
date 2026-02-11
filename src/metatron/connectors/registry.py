"""Connector registry — maps connector type strings to implementations.

Central registry for all connectors. Enterprise can register additional
connectors (SAPConnector, ServiceNowConnector) without modifying core.

Usage:
    registry = ConnectorRegistry()
    registry.register("confluence", ConfluenceConnector)
    connector = registry.create("confluence")
"""

from __future__ import annotations

import structlog

from metatron.core.interfaces import ConnectorInterface

logger = structlog.get_logger()


class ConnectorRegistry:
    """Type-safe registry mapping connector names to their classes.

    Thread-safe for reads. Registration happens at startup.
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[ConnectorInterface]] = {}

    def register(self, name: str, connector_cls: type[ConnectorInterface]) -> None:
        """Register a connector class under a given name.

        Args:
            name: Short identifier (e.g., "confluence", "jira").
            connector_cls: The connector class (not an instance).
        """
        if name in self._registry:
            logger.warning("connector.registry.overwrite", name=name)
        self._registry[name] = connector_cls
        logger.info("connector.registry.registered", name=name)

    def create(self, name: str) -> ConnectorInterface:
        """Create a new instance of a registered connector.

        Args:
            name: The connector type identifier.

        Returns:
            A fresh ConnectorInterface instance.

        Raises:
            KeyError: If name is not registered.
        """
        if name not in self._registry:
            available = list(self._registry.keys())
            msg = f"Unknown connector '{name}'. Available: {available}"
            raise KeyError(msg)
        return self._registry[name]()

    def list_available(self) -> list[str]:
        """Return sorted list of registered connector names."""
        return sorted(self._registry.keys())

    def is_registered(self, name: str) -> bool:
        """Check if a connector type is registered."""
        return name in self._registry


def register_builtins(registry: ConnectorRegistry) -> None:
    """Register all built-in connectors. Called at startup."""
    from metatron.connectors.confluence import ConfluenceConnector
    from metatron.connectors.files import FilesConnector
    from metatron.connectors.gdrive import GDriveConnector
    from metatron.connectors.github import GitHubConnector
    from metatron.connectors.jira import JiraConnector
    from metatron.connectors.notion import NotionConnector
    from metatron.connectors.slack_history import SlackHistoryConnector

    registry.register("confluence", ConfluenceConnector)
    registry.register("jira", JiraConnector)
    registry.register("notion", NotionConnector)
    registry.register("github", GitHubConnector)
    registry.register("gdrive", GDriveConnector)
    registry.register("slack_history", SlackHistoryConnector)
    registry.register("files", FilesConnector)
