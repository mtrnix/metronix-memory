"""PDF processor — extracts text using PyMuPDF (fitz)."""

from __future__ import annotations

import structlog

from metatron.core.interfaces import ProcessorInterface

logger = structlog.get_logger()


class PdfProcessor(ProcessorInterface):
    """Extracts text from PDF files using PyMuPDF.

    Handles multi-page documents. Preserves page breaks as double newlines.
    """

    def supported_types(self) -> list[str]:
        return ["application/pdf", ".pdf"]

    async def extract_text(self, content: bytes, filename: str) -> str:
        """Extract text from all pages of a PDF.

        Args:
            content: Raw PDF bytes.
            filename: Original filename.

        Returns:
            Concatenated text from all pages.
        """
        logger.info("processor.pdf.extract", filename=filename)
        # TODO: implement PDF text extraction
        # 1. fitz.open(stream=content, filetype="pdf")
        # 2. Iterate pages: doc.load_page(i).get_text()
        # 3. Join with double newlines between pages
        # 4. Strip excessive whitespace
        raise NotImplementedError("PDF extraction not yet implemented")
