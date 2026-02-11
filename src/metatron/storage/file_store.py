"""Local file storage with SHA-256 integrity verification.

Files are stored on disk, organized by workspace. Metadata goes to
PostgreSQL. Integrity is verified on read via SHA-256 checksums.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

from metatron.core.exceptions import IntegrityError

logger = structlog.get_logger()


class FileStore:
    """Disk-based file storage with integrity checks.

    Directory layout: {base_path}/{workspace_id}/{file_id}_{filename}
    """

    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path)

    async def save(
        self, workspace_id: str, file_id: str, filename: str, content: bytes
    ) -> tuple[str, str]:
        """Save file content to disk.

        Args:
            workspace_id: Workspace scope.
            file_id: Unique file identifier.
            filename: Original filename.
            content: Raw file bytes.

        Returns:
            Tuple of (storage_path, sha256_hex).
        """
        logger.info("file_store.save", workspace_id=workspace_id, file_id=file_id)
        # TODO: implement file save
        # 1. Create directory: self._base / workspace_id
        # 2. Write to: directory / f"{file_id}_{filename}"
        # 3. Compute SHA-256 of content
        # 4. Return (relative path, sha256 hex)
        ws_dir = self._base / workspace_id
        ws_dir.mkdir(parents=True, exist_ok=True)
        storage_name = f"{file_id}_{filename}"
        file_path = ws_dir / storage_name
        file_path.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()
        relative_path = f"{workspace_id}/{storage_name}"
        logger.info("file_store.saved", path=relative_path, sha256=sha256)
        return relative_path, sha256

    async def read(self, storage_path: str, expected_sha256: str) -> bytes:
        """Read file content and verify integrity.

        Args:
            storage_path: Relative path from save().
            expected_sha256: Expected SHA-256 hex digest.

        Returns:
            File content bytes.

        Raises:
            IntegrityError: If checksum doesn't match.
            FileNotFoundError: If file doesn't exist.
        """
        logger.info("file_store.read", path=storage_path)
        full_path = self._base / storage_path
        if not full_path.exists():
            msg = f"File not found: {storage_path}"
            raise FileNotFoundError(msg)
        content = full_path.read_bytes()
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise IntegrityError(
                f"SHA-256 mismatch for {storage_path}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        return content

    async def delete(self, storage_path: str) -> None:
        """Delete a file from disk.

        Args:
            storage_path: Relative path from save().
        """
        logger.info("file_store.delete", path=storage_path)
        full_path = self._base / storage_path
        if full_path.exists():
            full_path.unlink()
