"""
Confidence metric — response consistency via embedding similarity.

Generates N answers to the same question by calling
``hybrid_search_and_answer`` directly, embeds each answer via the
Embedding Proxy, and computes pairwise cosine similarity.

High similarity → model is confident (answers consistently).
Low similarity → model is uncertain (answers vary).

No UQLM / langchain dependencies — uses direct RAG calls instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import httpx
import numpy as np

from metatron.benchmarker.schemas.test_result import ConfidenceResult
from metatron.retrieval.search import hybrid_search_and_answer

logger = logging.getLogger(__name__)

NUM_RESPONSES = 5


class ConfidenceMetric:
    """RAG confidence via consistency of multiple responses.

    For each question:
    1. Call ``hybrid_search_and_answer`` NUM_RESPONSES times
    2. Embed each answer via Embedding Proxy
    3. Compute pairwise cosine similarity
    4. Normalize average similarity to [0, 1]
    """

    def __init__(
        self,
        embedding_base_url: str = "http://localhost:8001",
        embedding_model: str = "nomic-embed-text",
        concurrent_requests: int = 2,
        timeout: float = 60.0,
    ) -> None:
        self.embedding_base_url = embedding_base_url.rstrip("/")
        self.embeddings_url = f"{self.embedding_base_url}/v1/embeddings"
        self.embedding_model = embedding_model
        self.concurrent_requests = concurrent_requests
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrent_requests)

        logger.info(
            "ConfidenceMetric initialized: embeddings=%s, num_responses=%d",
            self.embeddings_url,
            NUM_RESPONSES,
        )

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text via Embedding Proxy."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.embeddings_url,
                    headers={"Content-Type": "application/json"},
                    json={"model": self.embedding_model, "input": text},
                )
                if response.status_code == 200:
                    return response.json()["data"][0]["embedding"]
                logger.error("Embedding API error: %d", response.status_code)
                return []
        except Exception as exc:
            logger.error("Error getting embedding: %s", exc)
            return []

    async def _get_embeddings_batch(
        self, texts: List[str],
    ) -> List[List[float]]:
        """Get embeddings for a list of texts in parallel."""
        tasks = [self._get_embedding(text) for text in texts]
        return await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Similarity calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Cosine similarity between two vectors."""
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        dot = np.dot(v1, v2)
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(dot / (n1 * n2))

    @staticmethod
    def _calculate_confidence_from_embeddings(
        embeddings: List[List[float]],
    ) -> dict:
        """Calculate confidence score from pairwise cosine similarity."""
        n = len(embeddings)
        if n < 2:
            return {
                "score": 1.0,
                "avg_similarity": 1.0,
                "min_similarity": None,
                "max_similarity": None,
            }

        similarities = []
        for i in range(n):
            for j in range(i + 1, n):
                sim = ConfidenceMetric._cosine_similarity(
                    embeddings[i], embeddings[j],
                )
                similarities.append(sim)

        avg_sim = float(np.mean(similarities))
        # Normalize from [-1, 1] to [0, 1]
        confidence = (avg_sim + 1) / 2

        return {
            "score": confidence,
            "avg_similarity": avg_sim,
            "min_similarity": float(np.min(similarities)),
            "max_similarity": float(np.max(similarities)),
        }

    # ------------------------------------------------------------------
    # Response generation (replaces UQLM)
    # ------------------------------------------------------------------

    def _generate_single_response(
        self, question: str, workspace_id: str,
    ) -> str:
        """Generate one answer via hybrid_search_and_answer (sync)."""
        try:
            answer = hybrid_search_and_answer(
                query=question,
                workspace_id=workspace_id,
            )
            return str(answer)
        except Exception as exc:
            logger.error("Error generating response: %s", exc)
            return ""

    async def _generate_responses(
        self, question: str, workspace_id: str,
    ) -> List[str]:
        """Generate NUM_RESPONSES answers by calling RAG multiple times."""
        responses: List[str] = []
        for i in range(NUM_RESPONSES):
            answer = await asyncio.to_thread(
                self._generate_single_response, question, workspace_id,
            )
            if answer:
                responses.append(answer)
        logger.info(
            "Generated %d/%d responses for confidence", len(responses), NUM_RESPONSES,
        )
        return responses

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def _calculate_single(
        self, question: str, workspace_id: str,
    ) -> ConfidenceResult:
        """Calculate confidence for a single question."""
        async with self.semaphore:
            try:
                responses = await self._generate_responses(question, workspace_id)

                if len(responses) < 2:
                    logger.warning(
                        "Not enough responses (%d), returning default",
                        len(responses),
                    )
                    return ConfidenceResult(
                        score=0.5, avg_similarity=0.0, num_responses=len(responses),
                    )

                embeddings = await self._get_embeddings_batch(responses)

                # Filter out empty embeddings
                valid = [
                    (r, e) for r, e in zip(responses, embeddings) if e
                ]
                if len(valid) < 2:
                    logger.warning("Not enough valid embeddings")
                    return ConfidenceResult(
                        score=0.5, avg_similarity=0.0, num_responses=len(valid),
                    )

                valid_embeddings = [e for _, e in valid]
                result = self._calculate_confidence_from_embeddings(valid_embeddings)

                return ConfidenceResult(
                    score=result["score"],
                    avg_similarity=result["avg_similarity"],
                    min_similarity=result["min_similarity"],
                    max_similarity=result["max_similarity"],
                    num_responses=len(valid_embeddings),
                )

            except Exception as exc:
                logger.error("Error calculating confidence: %s", exc, exc_info=True)
                return ConfidenceResult(
                    score=0.5, avg_similarity=0.0, num_responses=0,
                )

    async def calculate_batch(
        self,
        questions: List[str],
        workspace_id: Optional[str] = None,
    ) -> List[ConfidenceResult]:
        """Calculate confidence for a batch of questions.

        Args:
            questions: List of question texts.
            workspace_id: Workspace to query RAG against.

        Returns:
            List of :class:`ConfidenceResult`.
        """
        logger.info("Calculating confidence for %d questions", len(questions))

        results: List[ConfidenceResult] = []
        for idx, question in enumerate(questions, 1):
            logger.info(
                "Confidence %d/%d: %.50s...", idx, len(questions), question,
            )
            result = await self._calculate_single(question, workspace_id or "")
            results.append(result)

        if results:
            avg_score = sum(r.score for r in results) / len(results)
            logger.info("Confidence calculated: avg_score=%.3f", avg_score)

        return results

    def __str__(self) -> str:
        return f"ConfidenceMetric(num_responses={NUM_RESPONSES})"

    def __repr__(self) -> str:
        return (
            f"ConfidenceMetric("
            f"embedding_url='{self.embedding_base_url}', "
            f"num_responses={NUM_RESPONSES})"
        )
