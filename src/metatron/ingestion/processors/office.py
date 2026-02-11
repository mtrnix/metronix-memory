"""Office document processor — .docx (python-docx), .xlsx (openpyxl)."""

from __future__ import annotations

import structlog

from metatron.core.interfaces import ProcessorInterface

logger = structlog.get_logger()


class OfficeProcessor(ProcessorInterface):
    """Extracts text from Microsoft Office documents.

    Supports:
    - .docx: Extracts paragraph text via python-docx
    - .xlsx: Extracts cell values as tab-separated rows via openpyxl
    """

    def supported_types(self) -> list[str]:
        return [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".docx",
            ".xlsx",
        ]

    async def extract_text(self, content: bytes, filename: str) -> str:
        """Extract text from a .docx or .xlsx file.

        Args:
            content: Raw file bytes.
            filename: Used to determine format (.docx vs .xlsx).

        Returns:
            Extracted plain text.
        """
        logger.info("processor.office.extract", filename=filename)
        if filename.endswith(".docx"):
            return await self._extract_docx(content)
        elif filename.endswith(".xlsx"):
            return await self._extract_xlsx(content)
        else:
            msg = f"Unsupported office format: {filename}"
            raise ValueError(msg)

    async def _extract_docx(self, content: bytes) -> str:
        """Extract text from a .docx file.

        Uses python-docx to iterate paragraphs.
        """
        # TODO: implement .docx extraction
        # 1. io.BytesIO(content) → docx.Document()
        # 2. Iterate doc.paragraphs → paragraph.text
        # 3. Join with newlines
        raise NotImplementedError("DOCX extraction not yet implemented")

    async def _extract_xlsx(self, content: bytes) -> str:
        """Extract text from a .xlsx file.

        Iterates all sheets, rows, and cells. Outputs tab-separated values.
        """
        # TODO: implement .xlsx extraction
        # 1. io.BytesIO(content) → openpyxl.load_workbook(data_only=True)
        # 2. Iterate sheets → rows → cells
        # 3. Convert cell values to strings, join with tabs/newlines
        raise NotImplementedError("XLSX extraction not yet implemented")
