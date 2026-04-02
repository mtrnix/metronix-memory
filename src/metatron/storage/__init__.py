"""Storage layer — data access for all backends. Depends only on core."""

from metatron.storage.encryption import decrypt_value, encrypt_value
from metatron.storage.file_store import FileStore
from metatron.storage.neo4j_graph import (
    close_graph_driver,
    delete_workspace_graph,
    extract_graph_from_text,
    get_graph_driver,
    write_doc_graph,
)
from metatron.storage.qdrant import QdrantVectorStore, get_collection_name

__all__ = [
    "QdrantVectorStore",
    "get_graph_driver",
    "close_graph_driver",
    "extract_graph_from_text",
    "write_doc_graph",
    "delete_workspace_graph",
    "get_collection_name",
    "FileStore",
    "encrypt_value",
    "decrypt_value",
]
