from __future__ import annotations

import os
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType


class ExportArchiveWriter:
    """Stream text entries into a ZIP on disk. Use as a context manager."""

    def __init__(self, dest_path: str) -> None:
        self._dest = dest_path
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        self._zip: zipfile.ZipFile | None = None
        self.size_bytes = 0

    def __enter__(self) -> ExportArchiveWriter:
        self._zip = zipfile.ZipFile(self._dest, "w", compression=zipfile.ZIP_DEFLATED)
        return self

    def write_text(self, arcname: str, text: str) -> None:
        assert self._zip is not None, "writer is closed"
        self._zip.writestr(arcname, text)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None
        try:
            self.size_bytes = os.path.getsize(self._dest)
        except OSError:
            self.size_bytes = 0
