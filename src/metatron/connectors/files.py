"""Files connector — indexes uploaded files from local file store.

Unlike other connectors, this one reads from the local FileStore
rather than an external API. Used for manually uploaded documents.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document
from metatron.storage.file_store import FileStore

logger = structlog.get_logger()


class FilesConnector(ConnectorInterface):
    """Indexes files already stored in the local FileStore.

    Config keys (decrypted_config):
    - file_store_path: Base path for file storage (from Settings).
    """

    source_role: str = "user_upload"

    def __init__(self) -> None:
        self._file_store: FileStore | None = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize file store reference."""
        logger.info("files.configure", connector_id=connection.id)
        self._config = decrypted_config
        self._file_store = FileStore(decrypted_config.get("file_store_path", "./data/files"))

    async def fetch(self, workspace_id: str, since: datetime | None = None) -> list[Document]:
        """List files in the workspace directory and build Documents.

        Args:
            workspace_id: Target workspace (also the subdirectory).
            since: If set, only return files modified after this time.
        """
        logger.info("files.fetch.started", workspace_id=workspace_id, since=since)
        # TODO: implement file listing
        # 1. List files in self._file_store._base / workspace_id
        # 2. Filter by mtime if since is provided
        # 3. Read each file, build Document with filename, content type
        raise NotImplementedError("Files fetch not yet implemented")

    async def health_check(self) -> bool:
        """Check file store directory is accessible."""
        logger.info("files.health_check")
        if self._file_store is None:
            return False
        return self._file_store._base.exists()
