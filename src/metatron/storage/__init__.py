"""Storage layer — data access for all backends. Depends only on core."""

from metatron.storage.encryption import decrypt_value, encrypt_value
from metatron.storage.file_store import FileStore
from metatron.storage.memgraph import (
    close_memgraph_driver,
    delete_workspace_graph,
    extract_graph_from_text,
    get_memgraph_driver,
    write_doc_graph_to_memgraph,
)
from metatron.storage.qdrant import QdrantVectorStore, get_collection_name
from metatron.storage.redis import RedisStore

__all__ = [
    "QdrantVectorStore",
    "get_memgraph_driver",
    "close_memgraph_driver",
    "extract_graph_from_text",
    "write_doc_graph_to_memgraph",
    "delete_workspace_graph",
    "get_collection_name",
    "FileStore",
    "RedisStore",
    "encrypt_value",
    "decrypt_value",
]
