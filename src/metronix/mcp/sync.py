"""MCP sync manager — orchestrates fetching from MCP servers into the pipeline.

Supports hash-based incremental sync: tracks content hashes per source_id
so unchanged documents are skipped on re-sync.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import structlog

from metronix.core.models import Document, SyncResult
from metronix.mcp.adapter import get_adapter
from metronix.mcp.config import MCPServerConfig
from metronix.mcp.registry import MCPServerRegistry

logger = structlog.get_logger()


class MCPSyncManager:
    """Manages sync operations for MCP servers.

    Coordinates: registry → adapter → pipeline, with hash-based
    incremental sync to skip unchanged content.
    """

    def __init__(
        self,
        registry: MCPServerRegistry | None = None,
        state_dir: str = ".metronix",
    ) -> None:
        self._registry = registry or MCPServerRegistry(state_dir)
        self._hash_file = Path(state_dir) / "mcp_hashes.json"
        self._hash_file.parent.mkdir(parents=True, exist_ok=True)
        self._hashes: dict[str, str] = self._load_hashes()

    def _load_hashes(self) -> dict[str, str]:
        """Load content hashes from disk."""
        if not self._hash_file.exists():
            return {}
        try:
            return json.loads(self._hash_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("mcp.sync.hash_load_error", error=str(e))
            return {}

    def _save_hashes(self) -> None:
        """Persist content hashes to disk."""
        self._hash_file.write_text(json.dumps(self._hashes, indent=2))

    @staticmethod
    def _content_hash(text: str) -> str:
        """SHA-256 hash of document content for change detection."""
        return hashlib.sha256(text.encode()).hexdigest()

    def _filter_changed(self, documents: list[Document]) -> list[Document]:
        """Filter out documents whose content hasn't changed since last sync.

        Args:
            documents: Documents fetched from MCP server.

        Returns:
            Only documents with new or changed content.
        """
        changed: list[Document] = []
        for doc in documents:
            new_hash = self._content_hash(doc.content)
            old_hash = self._hashes.get(doc.source_id)
            if new_hash != old_hash:
                self._hashes[doc.source_id] = new_hash
                changed.append(doc)
            else:
                logger.debug(
                    "mcp.sync.skipped_unchanged",
                    source_id=doc.source_id,
                )
        return changed

    async def sync_server(
        self,
        config: MCPServerConfig,
        workspace_id: str,
        force_full: bool = False,
    ) -> SyncResult:
        """Sync a single MCP server: fetch → filter → ingest.

        Args:
            config: Server configuration.
            workspace_id: Target workspace.
            force_full: If True, skip hash-based filtering.

        Returns:
            SyncResult with ingestion statistics.
        """
        from metronix.ingestion.pipeline import ingest_documents

        logger.info(
            "mcp.sync.start",
            server=config.name,
            workspace_id=workspace_id,
            force_full=force_full,
        )

        adapter = get_adapter(config)
        all_docs = await adapter.fetch_documents(workspace_id)

        if not all_docs:
            logger.info("mcp.sync.no_documents", server=config.name)
            return SyncResult(
                connector_type=f"mcp:{config.name}",
                workspace_id=workspace_id,
                documents_fetched=0,
            )

        if force_full:
            docs_to_ingest = all_docs
            # Update hashes for all docs
            for doc in docs_to_ingest:
                self._hashes[doc.source_id] = self._content_hash(doc.content)
        else:
            docs_to_ingest = self._filter_changed(all_docs)

        self._save_hashes()

        if not docs_to_ingest:
            logger.info(
                "mcp.sync.all_unchanged",
                server=config.name,
                fetched=len(all_docs),
            )
            return SyncResult(
                connector_type=f"mcp:{config.name}",
                workspace_id=workspace_id,
                documents_fetched=len(all_docs),
                documents_skipped=len(all_docs),
            )

        result = await ingest_documents(
            docs_to_ingest,
            workspace_id,
            connector_type=f"mcp:{config.name}",
            incremental=not force_full,
        )

        logger.info(
            "mcp.sync.done",
            server=config.name,
            fetched=len(all_docs),
            ingested=len(docs_to_ingest),
            new=result.documents_new,
            updated=result.documents_updated,
        )
        return result

    async def sync_all(
        self,
        workspace_id: str,
        force_full: bool = False,
    ) -> list[tuple[str, SyncResult]]:
        """Sync all enabled MCP servers for a workspace.

        Args:
            workspace_id: Target workspace.
            force_full: If True, skip hash-based filtering for all servers.

        Returns:
            List of (server_name, SyncResult) tuples.
        """
        servers = self._registry.list_enabled(workspace_id)
        if not servers:
            logger.info("mcp.sync_all.no_servers", workspace_id=workspace_id)
            return []

        results: list[tuple[str, SyncResult]] = []
        for config in servers:
            try:
                result = await self.sync_server(config, workspace_id, force_full)
                results.append((config.name, result))
            except Exception as e:
                logger.error(
                    "mcp.sync_all.error",
                    server=config.name,
                    error=str(e),
                    exc_info=True,
                )
                results.append(
                    (
                        config.name,
                        SyncResult(
                            connector_type=f"mcp:{config.name}",
                            workspace_id=workspace_id,
                            errors=[str(e)],
                        ),
                    )
                )

        return results
