"""ingest_documents wires METRONIX_MEMORY_DUPLICATE_HAMMING_THRESHOLD into the
dedup index it constructs (#496) — it used to always take DeduplicationIndex's
hardcoded default regardless of the setting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from metronix.core.models import Document


def _make_doc(content: str = "Some content", source_id: str = "doc1") -> Document:
    return Document(
        id=source_id,
        workspace_id="ws_test",
        source_type="confluence",
        source_id=source_id,
        title="Test Doc",
        content=content,
    )


@patch("metronix.ingestion.pipeline._register_persons")
@patch("metronix.ingestion.pipeline._extract_graphs_parallel")
@patch("metronix.ingestion.pipeline.DeduplicationIndex")
@patch("metronix.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
async def test_dedup_index_uses_configured_threshold(
    mock_store_fn,
    mock_dedup_cls,
    mock_graph,
    mock_persons,
) -> None:
    from metronix.ingestion.pipeline import ingest_documents

    mock_store = AsyncMock()
    mock_store_fn.return_value = mock_store
    mock_dedup_cls.return_value.check_and_add.return_value = False

    with patch("metronix.core.config.Settings") as mock_settings_cls:
        s = mock_settings_cls.return_value
        s.memory_duplicate_hamming_threshold = 7
        s.hierarchical_chunking_enabled = False
        s.graph_extraction_enabled = False

        await ingest_documents([_make_doc()], workspace_id="ws_test")

    mock_dedup_cls.assert_called_once_with(threshold=7)


@patch("metronix.ingestion.pipeline._register_persons")
@patch("metronix.ingestion.pipeline._extract_graphs_parallel")
@patch("metronix.ingestion.pipeline.DeduplicationIndex")
@patch("metronix.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
async def test_dedup_index_uses_a_different_configured_threshold(
    mock_store_fn,
    mock_dedup_cls,
    mock_graph,
    mock_persons,
) -> None:
    """Same as above with a different value, so the test can't pass by accident
    (e.g. by asserting against DeduplicationIndex's own default of 3)."""
    from metronix.ingestion.pipeline import ingest_documents

    mock_store = AsyncMock()
    mock_store_fn.return_value = mock_store
    mock_dedup_cls.return_value.check_and_add.return_value = False

    with patch("metronix.core.config.Settings") as mock_settings_cls:
        s = mock_settings_cls.return_value
        s.memory_duplicate_hamming_threshold = 12
        s.hierarchical_chunking_enabled = False
        s.graph_extraction_enabled = False

        await ingest_documents([_make_doc()], workspace_id="ws_test")

    mock_dedup_cls.assert_called_once_with(threshold=12)
