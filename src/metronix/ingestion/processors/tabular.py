"""Tabular data processing (CSV, Excel).

Converts tabular data to key-value text format suitable for RAG indexing.
Each row becomes ``Row N: Col1: Val1, Col2: Val2, ...`` for better
semantic search over structured content.
"""

from __future__ import annotations

import io

import pandas as pd
import structlog

logger = structlog.get_logger()


def parse_csv(content: bytes, encoding: str = "utf-8") -> pd.DataFrame:
    """Parse CSV bytes into a DataFrame, trying fallback encodings on failure."""
    try:
        return pd.read_csv(io.BytesIO(content), encoding=encoding)
    except UnicodeDecodeError:
        for enc in ["cp1251", "latin-1", "utf-16"]:
            try:
                return pd.read_csv(io.BytesIO(content), encoding=enc)
            except (UnicodeDecodeError, Exception):
                continue
        raise ValueError("Could not decode CSV with any supported encoding") from None


def parse_excel(content: bytes) -> pd.DataFrame:
    """Parse Excel bytes into a DataFrame (first sheet, openpyxl engine)."""
    return pd.read_excel(io.BytesIO(content), engine="openpyxl")


def dataframe_to_text(
    df: pd.DataFrame,
    max_rows: int | None = None,
    include_row_numbers: bool = True,
) -> str:
    """Convert a DataFrame to key-value text.

    Each row becomes a line like::

        Row 1: Column1: Value1, Column2: Value2

    Args:
        df: Input DataFrame.
        max_rows: Truncate after this many rows (``None`` = all).
        include_row_numbers: Prefix each line with ``Row N:``.

    Returns:
        Text representation of the table.
    """
    if df.empty:
        return ""

    df.columns = [str(col).strip() for col in df.columns]

    if max_rows and len(df) > max_rows:
        df = df.head(max_rows)
        logger.warning("tabular.truncated", max_rows=max_rows)

    lines: list[str] = []
    for idx, row in df.iterrows():
        pairs: list[str] = []
        for col in df.columns:
            value = row[col]
            if pd.isna(value) or str(value).strip() == "":
                continue
            value_str = str(value).strip()
            if len(value_str) > 500:
                value_str = value_str[:500] + "..."
            pairs.append(f"{col}: {value_str}")

        if pairs:
            row_text = ", ".join(pairs)
            if include_row_numbers:
                row_num = idx + 1 if isinstance(idx, int) else idx
                lines.append(f"Row {row_num}: {row_text}")
            else:
                lines.append(row_text)

    return "\n".join(lines)


def process_tabular_file(  # TODO: async migration
    content: bytes,
    filename: str,
    max_rows: int | None = 10000,
) -> tuple[str, dict]:
    """Process a CSV or Excel file and convert to text.

    Args:
        content: Raw file bytes.
        filename: Original filename (used to detect format).
        max_rows: Maximum rows to process.

    Returns:
        ``(text_content, metadata)`` tuple.

    Raises:
        ValueError: If the file format is not supported.
    """
    filename_lower = filename.lower()

    if filename_lower.endswith(".csv"):
        df = parse_csv(content)
        file_type = "csv"
    elif filename_lower.endswith((".xlsx", ".xls")):
        df = parse_excel(content)
        file_type = "excel"
    else:
        raise ValueError(f"Unsupported tabular format: {filename}")

    text = dataframe_to_text(df, max_rows=max_rows)

    metadata = {
        "type": file_type,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }

    logger.info(
        "tabular.processed",
        file_type=file_type,
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
    )

    return text, metadata


def is_tabular_file(filename: str) -> bool:
    """Return ``True`` if *filename* indicates a tabular format."""
    return filename.lower().endswith((".csv", ".xlsx", ".xls"))
