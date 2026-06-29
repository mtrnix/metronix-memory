"""Document sampler — adapter from Metronix Core connectors to BenchmarkQED.

Bridges ConnectorInterface (fetch documents from external sources) with the
QEDDocument format expected by the benchmark question generator.
"""

from __future__ import annotations

import random

import structlog

from metronix.benchmarker.schemas.benchmark import QEDDocument
from metronix.connectors.registry import ConnectorRegistry
from metronix.core.models import Connection, Document

logger = structlog.get_logger()


class DocumentSampler:
    """Adapter: Metronix Core connectors → documents for BenchmarkQED."""

    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    async def sample_documents(
        self,
        connection: Connection,
        decrypted_config: dict[str, str],
        workspace_id: str,
        n: int,
    ) -> list[QEDDocument]:
        """Fetch documents via connector and sample *n* of them.

        Steps:
            1. Create connector via ``registry.create(connection.connector_type)``
            2. Call ``connector.configure(connection, decrypted_config)``
            3. Call ``connector.fetch(workspace_id)``
            4. Sample ``min(n, len(docs))`` documents
            5. Convert each ``Document`` → ``QEDDocument``

        Returns an empty list when the connector yields no documents.
        Returns all documents when *n* exceeds the available count.
        """
        connector = self._registry.create(connection.connector_type)
        await connector.configure(connection, decrypted_config)

        documents = await connector.fetch(workspace_id)

        if not documents:
            logger.info("No documents returned by connector %s", connection.connector_type)
            return []

        sampled = random.sample(documents, min(n, len(documents)))
        logger.info(
            "Sampled %d/%d documents from connector %s",
            len(sampled),
            len(documents),
            connection.connector_type,
        )
        return [self._to_qed(doc) for doc in sampled]

    @staticmethod
    def _to_qed(doc: Document) -> QEDDocument:
        """Map a Metronix ``Document`` to the ``QEDDocument`` format.

        Field mapping:
            source_id  → source_id
            title      → title
            content    → text
            source_type → source_type
            url        → url
        """
        return QEDDocument(
            source_id=doc.source_id,
            title=doc.title,
            text=doc.content,
            source_type=doc.source_type,
            url=doc.url,
        )
