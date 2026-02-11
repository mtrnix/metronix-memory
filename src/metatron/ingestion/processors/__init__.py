"""Document processors for various file formats."""

from metatron.ingestion.processors.html import process_html
from metatron.ingestion.processors.dates import extract_date_from_text, extract_date_range
from metatron.ingestion.processors.tabular import process_tabular_file, is_tabular_file
from metatron.ingestion.processors.titles import extract_title_from_body, extract_title_from_markdown
from metatron.ingestion.processors.translation import (
    is_russian, is_english, translate_to_english, translate_to_russian,
)
from metatron.ingestion.processors.office import OfficeProcessor
from metatron.ingestion.processors.pdf import PdfProcessor
from metatron.ingestion.processors.text import TextProcessor

__all__ = [
    "process_html",
    "extract_date_from_text",
    "extract_date_range",
    "process_tabular_file",
    "is_tabular_file",
    "extract_title_from_body",
    "extract_title_from_markdown",
    "is_russian",
    "is_english",
    "translate_to_english",
    "translate_to_russian",
    "TextProcessor",
    "PdfProcessor",
    "OfficeProcessor",
]
