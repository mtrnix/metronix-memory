"""PDF processor — extracts text and tables using PyMuPDF (fitz).

Two-stage extraction:
1. find_tables() → each table as markdown (content_type="table")
2. get_text() for remaining prose (content_type="text")
"""

from __future__ import annotations

import re
from typing import TypedDict

import structlog

from metronix.core.interfaces import ProcessorInterface

logger = structlog.get_logger()

# Collapse runs of 3+ newlines into 2
_EXCESS_NEWLINES = re.compile(r"\n{3,}")

# Pattern: COMPANY_YEAR[Q#]_DOCTYPE[_extra].pdf
_FILENAME_RE = re.compile(
    r"^(?P<company>[A-Z0-9][A-Z0-9&]+?)_(?P<year>\d{4})(?:Q\d)?_(?P<doctype>[A-Za-z0-9_-]+)"
)


class PageBlock(TypedDict, total=False):
    text: str
    content_type: str  # "table" or "text"
    page: int


def parse_financial_metadata(filename: str) -> dict[str, str]:
    """Extract company, fiscal_year, doc_type from filename.

    Examples:
        "3M_2018_10K.pdf" → {"company": "3M", "fiscal_year": "2018", "doc_type": "10K"}
        "AMCOR_2022_8K_2022-04-26.pdf" → {"company": "AMCOR", ...}
    """
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    m = _FILENAME_RE.match(stem)
    if not m:
        return {}
    return {
        "company": m.group("company"),
        "fiscal_year": m.group("year"),
        "doc_type": m.group("doctype").split("_")[0].upper(),
    }


_MIN_TABLE_ROWS = 3
_MIN_TABLE_CHARS = 200


def _extract_page_blocks(page) -> list[PageBlock]:
    """Extract text + significant tables from a single page.

    Only tables with >= 3 rows and >= 200 chars are kept as separate
    markdown blocks. This filters out formatting micro-tables (headers,
    footers, single-row layouts) that financial PDFs are full of.
    """
    blocks: list[PageBlock] = []
    page_num = page.number

    # 1. Always extract full page text
    text = page.get_text()
    if text and text.strip():
        blocks.append(
            PageBlock(
                text=text.strip(),
                content_type="text",
                page=page_num,
            )
        )

    # 2. Extract only significant tables as bonus markdown chunks
    try:
        tables = page.find_tables()
        for table in tables:
            md = table.to_markdown()
            if not md or not md.strip():
                continue
            row_count = md.strip().count("\n")
            if row_count < _MIN_TABLE_ROWS or len(md) < _MIN_TABLE_CHARS:
                continue
            blocks.append(
                PageBlock(
                    text=md.strip(),
                    content_type="table",
                    page=page_num,
                )
            )
    except Exception:
        pass  # find_tables can fail on malformed pages

    return blocks


def extract_text_from_pdf(content: bytes, filename: str = "document.pdf") -> str:
    """Extract text from PDF bytes using PyMuPDF.

    Returns concatenated text from all pages (backward-compatible).
    For structured extraction with tables, use extract_blocks_from_pdf().
    """
    import fitz

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Cannot open PDF '{filename}': {e}") from e

    pages: list[str] = []
    for page in doc:
        text = page.get_text()
        if text and text.strip():
            pages.append(text.strip())
    doc.close()

    if not pages:
        raise ValueError(f"PDF '{filename}' contains no extractable text")

    result = "\n\n".join(pages)
    result = _EXCESS_NEWLINES.sub("\n\n", result)
    logger.info("processor.pdf.extract", filename=filename, pages=len(pages), chars=len(result))
    return result


def extract_blocks_from_pdf(
    content: bytes,
    filename: str = "document.pdf",
) -> list[PageBlock]:
    """Extract structured blocks (text + tables) from PDF.

    Tables are extracted as markdown via find_tables(). Each page also
    yields its full text. Returns a flat list of PageBlock dicts.
    """
    import fitz

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Cannot open PDF '{filename}': {e}") from e

    all_blocks: list[PageBlock] = []
    table_count = 0
    for page in doc:
        blocks = _extract_page_blocks(page)
        for b in blocks:
            if b["content_type"] == "table":
                table_count += 1
        all_blocks.extend(blocks)
    doc.close()

    if not all_blocks:
        raise ValueError(f"PDF '{filename}' contains no extractable content")

    logger.info(
        "processor.pdf.extract_blocks",
        filename=filename,
        blocks=len(all_blocks),
        tables=table_count,
    )
    return all_blocks


class PdfProcessor(ProcessorInterface):
    """Extracts text from PDF files using PyMuPDF.

    Handles multi-page documents. Preserves page breaks as double newlines.
    """

    def supported_types(self) -> list[str]:
        return ["application/pdf", ".pdf"]

    async def extract_text(self, content: bytes, filename: str) -> str:
        return extract_text_from_pdf(content, filename)
