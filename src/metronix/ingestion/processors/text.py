"""Plain text processor — handles .txt, .md, .csv, .log files."""

from __future__ import annotations

import structlog

from metronix.core.interfaces import ProcessorInterface

logger = structlog.get_logger()


class TextProcessor(ProcessorInterface):
    """Extracts text from plain text files. Minimal processing."""

    def supported_types(self) -> list[str]:
        return ["text/plain", ".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml"]

    async def extract_text(self, content: bytes, filename: str) -> str:
        """Decode bytes to UTF-8 text.

        Handles common encodings. Falls back to latin-1 if UTF-8 fails.
        """
        logger.info("processor.text.extract", filename=filename)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1")
