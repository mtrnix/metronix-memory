"""Tests for metatron.ingestion.sync — BackgroundSyncManager and helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.core.models import Document, DocumentVersion
from metatron.ingestion.sync import BackgroundSyncManager, check_and_version_document


# ---------------------------------------------------------------------------
# check_and_version_document
# ---------------------------------------------------------------------------


class TestCheckAndVersionDocument:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_store(self) -> None:
        doc = Document(id="d1", content="hello")
        result = await check_and_version_document(doc, None, "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_store_lacks_method(self) -> None:
        doc = Document(id="d1", content="hello")
        store = MagicMock(spec=[])  # no store_document_version attr
        result = await check_and_version_document(doc, store, "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_version_when_no_previous(self) -> None:
        doc = Document(id="d1", content="hello")
        store = AsyncMock()
        store.get_latest_version = AsyncMock(return_value=None)
        store.store_document_version = AsyncMock(
            return_value=DocumentVersion(
                id="v1",
                document_id="d1",
                version_number=1,
                content="hello",
                sync_source="confluence",
            )
        )
        result = await check_and_version_document(doc, store, "confluence")
        assert result is not None
        assert result.version_number == 1

    @pytest.mark.asyncio
    async def test_creates_version_when_content_changed(self) -> None:
        doc = Document(id="d1", content="new content")
        old_version = DocumentVersion(
            id="v1",
            document_id="d1",
            version_number=1,
            content="old content",
            content_hash="different_hash",
        )
        store = AsyncMock()
        store.get_latest_version = AsyncMock(return_value=old_version)
        store.store_document_version = AsyncMock(
            return_value=DocumentVersion(
                id="v2",
                document_id="d1",
                version_number=2,
                content="new content",
                sync_source="jira",
            )
        )
        result = await check_and_version_document(doc, store, "jira")
        assert result is not None
        assert result.version_number == 2

    @pytest.mark.asyncio
    async def test_returns_none_when_unchanged(self) -> None:
        import hashlib

        content = "same content"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        doc = Document(id="d1", content=content)
        old_version = DocumentVersion(
            id="v1",
            document_id="d1",
            version_number=1,
            content=content,
            content_hash=content_hash,
        )
        store = AsyncMock()
        store.get_latest_version = AsyncMock(return_value=old_version)
        result = await check_and_version_document(doc, store, "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_not_implemented_gracefully(self) -> None:
        doc = Document(id="d1", content="hello")
        store = AsyncMock()
        store.get_latest_version = AsyncMock(side_effect=NotImplementedError)
        store.store_document_version = AsyncMock(side_effect=NotImplementedError)
        result = await check_and_version_document(doc, store, "test")
        assert result is None


# ---------------------------------------------------------------------------
# BackgroundSyncManager
# ---------------------------------------------------------------------------


class TestBackgroundSyncManager:
    def test_init_defaults(self) -> None:
        mgr = BackgroundSyncManager()
        assert mgr.sync_interval == 3600
        assert mgr.sources == ["confluence", "jira", "notion"]
        assert mgr._running is False

    def test_init_custom(self) -> None:
        mgr = BackgroundSyncManager(
            sync_interval_seconds=60,
            sources=["github"],
        )
        assert mgr.sync_interval == 60
        assert mgr.sources == ["github"]

    def test_register_callback(self) -> None:
        mgr = BackgroundSyncManager()
        cb = AsyncMock()
        mgr.register_sync_callback("github", cb)
        assert "github" in mgr._sync_callbacks

    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        mgr = BackgroundSyncManager(sync_interval_seconds=9999)
        await mgr.start()
        assert mgr._running is True
        assert mgr._task is not None
        await mgr.stop()
        assert mgr._running is False

    @pytest.mark.asyncio
    async def test_double_start_ignored(self) -> None:
        mgr = BackgroundSyncManager(sync_interval_seconds=9999)
        await mgr.start()
        task1 = mgr._task
        await mgr.start()  # Should be no-op
        assert mgr._task is task1
        await mgr.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        mgr = BackgroundSyncManager()
        await mgr.stop()  # Should be no-op, no exception

    @pytest.mark.asyncio
    async def test_sync_source_without_callback(self) -> None:
        mgr = BackgroundSyncManager(sources=["unknown"])
        result = await mgr._sync_source("unknown")
        assert result["status"] == "no_callback"

    @pytest.mark.asyncio
    async def test_sync_source_with_callback(self) -> None:
        mgr = BackgroundSyncManager()
        cb = AsyncMock(return_value={"docs": 5})
        mgr.register_sync_callback("github", cb)
        result = await mgr._sync_source("github")
        assert result == {"docs": 5}
        cb.assert_awaited_once_with("github")

    @pytest.mark.asyncio
    async def test_sync_all_sources_handles_errors(self) -> None:
        mgr = BackgroundSyncManager(sources=["good", "bad"])
        mgr.register_sync_callback("good", AsyncMock(return_value={"ok": True}))
        mgr.register_sync_callback("bad", AsyncMock(side_effect=RuntimeError("fail")))
        # Should not raise — errors are logged
        await mgr.sync_all_sources()
