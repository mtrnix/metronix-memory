"""Tests for file download endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import metatron.core.config as config_module
from metatron.api.routes.files import router


@pytest.fixture
def file_store_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def client(file_store_dir):
    """Create test client with overridden file_store_path."""
    mock_settings = MagicMock()
    mock_settings.file_store_path = file_store_dir

    original = config_module._settings
    config_module._settings = mock_settings
    try:
        app = FastAPI()
        # Router already has prefix="/files", mount under /api/v1
        app.include_router(router, prefix="/api/v1")
        yield TestClient(app)
    finally:
        config_module._settings = original


class TestFileDownload:
    def test_download_existing_file(self, client, file_store_dir) -> None:
        ws_dir = Path(file_store_dir) / "ws1"
        ws_dir.mkdir()
        (ws_dir / "abc123_report.pdf").write_bytes(b"%PDF-fake-content")

        resp = client.get("/api/v1/files/abc123/download", params={"workspace_id": "ws1"})
        assert resp.status_code == 200
        assert resp.content == b"%PDF-fake-content"
        assert "report.pdf" in resp.headers.get("content-disposition", "")

    def test_download_nonexistent_file_returns_404(self, client, file_store_dir) -> None:
        ws_dir = Path(file_store_dir) / "ws1"
        ws_dir.mkdir()

        resp = client.get("/api/v1/files/nonexistent/download", params={"workspace_id": "ws1"})
        assert resp.status_code == 404

    def test_download_nonexistent_workspace_returns_404(self, client, file_store_dir) -> None:
        resp = client.get("/api/v1/files/abc123/download", params={"workspace_id": "nope"})
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, client, file_store_dir) -> None:
        resp = client.get(
            "/api/v1/files/abc123/download",
            params={"workspace_id": "../../etc"},
        )
        assert resp.status_code == 404
