"""L3 read-only facade for KB raw_documents.

Exposes raw_documents to the unified knowledge endpoint without touching
the existing ingestion or retrieval paths. Write-free by design: all
mutations go through the ingestion pipeline and connector sync.

Re-exports:
    RawDocumentReadService
"""

from metatron.knowledge.service import RawDocumentReadService

__all__ = ["RawDocumentReadService"]
