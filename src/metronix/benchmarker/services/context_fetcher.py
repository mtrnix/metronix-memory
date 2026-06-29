"""
Context Fetcher — fetch full chunk data from Qdrant by ID.

In the integrated version, white-box data (scores, fragments, graph entities)
comes from ``return_trace=True`` on ``hybrid_search_and_answer()``.
ContextFetcher only needs to retrieve the full chunk text from Qdrant
so that metric calculators have the raw content available.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import structlog

from metronix.benchmarker.schemas.test_context import ChunkData

if TYPE_CHECKING:
    from metronix.core.config import Settings

logger = structlog.get_logger()


class ContextFetcher:
    """Fetch full chunk data from Qdrant by ID."""

    def __init__(
        self,
        qdrant_url: str,
        qdrant_collection: str = "mem_docs_hybrid",
        timeout: float = 30.0,
    ):
        self.qdrant_url = qdrant_url.rstrip("/")
        self.collection = qdrant_collection
        self.timeout = timeout

        logger.info(
            "ContextFetcher initialized: qdrant=%s, collection=%s",
            self.qdrant_url,
            self.collection,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> ContextFetcher:
        """Create a ContextFetcher from Metronix Settings."""
        qdrant_url = f"http://{settings.qdrant_host}:{settings.qdrant_http_port}"
        return cls(qdrant_url=qdrant_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_chunks(
        self,
        source_results: list[dict],
    ) -> list[ChunkData]:
        """
        Fetch full chunk data from Qdrant by IDs extracted from *source_results*.

        Each element in *source_results* is expected to carry an ``id`` key
        (the Qdrant point UUID) and optionally a ``score``.

        Returns a list of :class:`ChunkData` objects.  Chunks that cannot be
        found (404) are silently skipped.  If Qdrant is unreachable the method
        logs a warning and returns an empty list.
        """
        doc_ids = [sr.get("id") for sr in source_results if sr.get("id")]
        if not doc_ids:
            return []

        try:
            raw_points = await self._fetch_points_batch(doc_ids)
        except httpx.ConnectError:
            logger.warning(
                "Qdrant is unavailable at %s — returning empty chunk list",
                self.qdrant_url,
            )
            return []
        except Exception:
            logger.warning(
                "Unexpected error contacting Qdrant at %s — returning empty chunk list",
                self.qdrant_url,
                exc_info=True,
            )
            return []

        # Build a score lookup from source_results
        score_map: dict[str, float | None] = {}
        for sr in source_results:
            did = sr.get("id")
            if did:
                score_map[did] = sr.get("score")

        chunks: list[ChunkData] = []
        for doc_id, point_data in zip(doc_ids, raw_points, strict=False):
            if point_data is None:
                continue
            chunks.append(self._parse_chunk(point_data, score=score_map.get(doc_id)))
        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_points_batch(
        self,
        doc_ids: list[str],
    ) -> list[dict | None]:
        """Fetch multiple points from Qdrant in parallel."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            tasks = [
                client.get(f"{self.qdrant_url}/collections/{self.collection}/points/{doc_id}")
                for doc_id in doc_ids
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict | None] = []
        for doc_id, response in zip(doc_ids, responses, strict=False):
            if isinstance(response, Exception):
                logger.error("Error fetching chunk %s: %s", doc_id, response)
                results.append(None)
            elif response.status_code == 200:
                data = response.json()
                results.append(data.get("result"))
            elif response.status_code == 404:
                logger.warning("Chunk %s not found in Qdrant (404)", doc_id)
                results.append(None)
            else:
                logger.warning(
                    "Chunk %s returned unexpected status %s",
                    doc_id,
                    response.status_code,
                )
                results.append(None)
        return results

    @staticmethod
    def _parse_chunk(
        point_data: dict,
        score: float | None = None,
    ) -> ChunkData:
        """Convert raw Qdrant point data into a :class:`ChunkData`."""
        payload = point_data.get("payload", {})
        return ChunkData(
            id=point_data.get("id", ""),
            title=payload.get("title", "N/A"),
            data=payload.get("data", ""),
            doc_label=payload.get("doc_label", ""),
            score=score,
            chunk_num=payload.get("chunk"),
            type=payload.get("type"),
        )

    def __str__(self) -> str:
        return f"ContextFetcher(qdrant={self.qdrant_url})"

    def __repr__(self) -> str:
        return f"ContextFetcher(qdrant_url='{self.qdrant_url}', collection='{self.collection}')"
