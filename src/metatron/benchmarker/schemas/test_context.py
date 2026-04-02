"""
Test context schemas — holds per-question RAG output and white-box data.

Adapted from metatron-benchmarker for integration into Metatron Core.
In the integrated version, white-box data comes from ``return_trace=True``
on ``hybrid_search_and_answer()`` instead of a separate query log fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .benchmark import BenchmarkQuestion


@dataclass
class ChunkData:
    """Single chunk retrieved from Qdrant."""

    id: str
    title: str
    data: str  # chunk text content
    doc_label: str
    score: float | None = None
    chunk_num: int | None = None
    type: str | None = None


@dataclass
class TestContext:
    """
    Full context for a single test question.

    Contains the question, the RAG answer, latency measurement,
    and white-box retrieval data (source results, fragments, graph entities)
    obtained via ``hybrid_search_and_answer(return_trace=True)``.
    """

    # Core data
    question: BenchmarkQuestion
    answer: str
    latency_ms: float
    workspace_id: str | None = None

    # White-box data from return_trace
    source_results: list[dict] | None = field(default=None)
    fragments: list[str] | None = field(default=None)
    graph_entities: list[dict] | None = field(default=None)

    # Ground-truth doc_labels for retrieval metrics
    expected_doc_labels: set[str] | None = field(default=None)

    # Ordered retrieved doc_labels from search results
    retrieved_doc_labels: list[str] | None = field(default=None)

    # Chunk data fetched from Qdrant (populated by ContextFetcher)
    source_chunks: list[ChunkData] | None = field(default=None)
    enrichment_chunks: list[ChunkData] | None = field(default=None)

    @property
    def has_white_box_data(self) -> bool:
        """Check whether white-box retrieval data is available."""
        return self.source_results is not None and self.fragments is not None

    @property
    def all_chunks(self) -> list[ChunkData]:
        """Return all chunks (source + enrichment)."""
        chunks: list[ChunkData] = []
        if self.source_chunks:
            chunks.extend(self.source_chunks)
        if self.enrichment_chunks:
            chunks.extend(self.enrichment_chunks)
        return chunks

    @property
    def context_text(self) -> str:
        """Concatenated text of all chunks for metric calculations."""
        return "\n\n".join(chunk.data for chunk in self.all_chunks)

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "question": self.question.model_dump(),
            "answer": self.answer,
            "latency_ms": self.latency_ms,
            "has_white_box_data": self.has_white_box_data,
            "source_chunks_count": len(self.source_chunks) if self.source_chunks else 0,
            "enrichment_chunks_count": len(self.enrichment_chunks)
            if self.enrichment_chunks
            else 0,
        }
