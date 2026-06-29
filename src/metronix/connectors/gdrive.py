"""Google Drive connector — fetches documents via Drive API.

Uses google-api-python-client with service account or OAuth credentials.
Supports Google Docs, Sheets (exported as text), and uploaded files.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from metronix.core.interfaces import ConnectorInterface
from metronix.core.models import Connection, Document

logger = structlog.get_logger()


class GDriveConnector(ConnectorInterface):
    """Fetches files from Google Drive shared drives or folders.

    Config keys (decrypted_config):
    - credentials_json: Path to service account JSON file
    - folder_id: (optional) Root folder ID to index
    - shared_drive_id: (optional) Shared drive ID
    """

    def __init__(self) -> None:
        self._service = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize Google Drive API service."""
        logger.info("gdrive.configure", connector_id=connection.id)
        self._config = decrypted_config
        # TODO: implement service initialization
        # 1. Load credentials from JSON file path
        # 2. Build Drive API v3 service
        # google.oauth2.service_account.Credentials.from_service_account_file()
        # googleapiclient.discovery.build("drive", "v3", credentials=creds)

    async def fetch(self, workspace_id: str, since: datetime | None = None) -> list[Document]:
        """Fetch files from Google Drive.

        Uses Drive API files.list with query for modified time.
        Exports Google Docs as plain text, downloads binary files.

        Args:
            workspace_id: Target workspace.
            since: If set, filter by modifiedTime > since.
        """
        logger.info("gdrive.fetch.started", workspace_id=workspace_id, since=since)
        # TODO: implement Drive file iteration
        # 1. Build query: mimeType != folder, modifiedTime > since
        # 2. Paginate through files.list (pageToken)
        # 3. Export Google Docs as text, download others
        # 4. Build Documents with filename, owner, shared drive info
        raise NotImplementedError("Google Drive fetch not yet implemented")

    async def health_check(self) -> bool:
        """Test Drive API connectivity."""
        logger.info("gdrive.health_check")
        return False
