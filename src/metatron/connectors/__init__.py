"""Connectors layer — data source adapters. Depends on core + storage + ingestion."""

from metatron.connectors.confluence import ConfluenceConnector
from metatron.connectors.files import FilesConnector
from metatron.connectors.gdrive import GDriveConnector
from metatron.connectors.github import GitHubConnector
from metatron.connectors.jira import JiraConnector
from metatron.connectors.notion import NotionConnector
from metatron.connectors.registry import ConnectorRegistry
from metatron.connectors.slack_history import SlackHistoryConnector

__all__ = [
    "ConnectorRegistry",
    "ConfluenceConnector",
    "JiraConnector",
    "NotionConnector",
    "GitHubConnector",
    "GDriveConnector",
    "SlackHistoryConnector",
    "FilesConnector",
]
