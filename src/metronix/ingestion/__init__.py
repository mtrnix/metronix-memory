"""Ingestion layer — document processing pipeline. Depends on core + storage."""

from metronix.ingestion.bm25 import (
    compute_bm25_sparse_vector,
    compute_query_sparse_vector,
    to_qdrant_sparse,
    tokenize,
)
from metronix.ingestion.chunking import root_child_chunk, simple_chunk
from metronix.ingestion.dedup import is_near_duplicate, simhash
from metronix.ingestion.pipeline import IngestionPipeline

__all__ = [
    "IngestionPipeline",
    "root_child_chunk",
    "simple_chunk",
    "simhash",
    "is_near_duplicate",
    "compute_bm25_sparse_vector",
    "compute_query_sparse_vector",
    "to_qdrant_sparse",
    "tokenize",
]
