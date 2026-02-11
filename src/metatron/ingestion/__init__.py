"""Ingestion layer — document processing pipeline. Depends on core + storage."""

from metatron.ingestion.bm25 import (
    compute_bm25_sparse_vector,
    compute_query_sparse_vector,
    to_qdrant_sparse,
    tokenize,
)
from metatron.ingestion.chunking import root_child_chunk, simple_chunk
from metatron.ingestion.dedup import is_near_duplicate, simhash
from metatron.ingestion.pipeline import IngestionPipeline

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
