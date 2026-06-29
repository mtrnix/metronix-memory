"""Connectors layer — data source adapters. Depends on core + storage + ingestion."""

from metronix.connectors.confluence import ConfluenceConnector
from metronix.connectors.files import FilesConnector
from metronix.connectors.gdrive import GDriveConnector
from metronix.connectors.github import GitHubConnector
from metronix.connectors.jira import JiraConnector
from metronix.connectors.notion import NotionConnector
from metronix.connectors.registry import ConnectorRegistry
from metronix.connectors.slack_history import SlackHistoryConnector

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
