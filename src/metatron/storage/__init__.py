"""Storage layer — data access for all backends. Depends only on core."""

from metatron.storage.encryption import decrypt_value, encrypt_value
from metatron.storage.file_store import FileStore
from metatron.storage.memgraph import (
    get_memgraph_driver,
    close_memgraph_driver,
    extract_graph_from_text,
    write_doc_graph_to_memgraph,
    delete_workspace_graph,
)
from metatron.storage.qdrant import QdrantVectorStore, get_collection_name

__all__ = [
    "QdrantVectorStore",
    "get_memgraph_driver",
    "close_memgraph_driver",
    "extract_graph_from_text",
    "write_doc_graph_to_memgraph",
    "delete_workspace_graph",
    "get_collection_name",
    "FileStore",
    "encrypt_value",
    "decrypt_value",
]
