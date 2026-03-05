"""
Answer Relevancy metric — cosine similarity of embeddings.

Measures how relevant the RAG answer is to the original question by
computing cosine similarity between their embedding vectors.  Embeddings
are obtained from the Embedding Proxy HTTP API (OpenAI-compatible).
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass
from typing import List, Optional

import httpx
import numpy as np

logger = structlog.get_logger()


@dataclass
class RelevancyResult:
    """Result of the Answer Relevancy metric evaluation."""

    score: float
    method: str = "embeddings"


class AnswerRelevancyMetric:
    """Answer relevancy via cosine similarity of embeddings.

    Uses the Embedding Proxy (OpenAI-compatible API) to obtain vector
    representations of questions and answers, then computes cosine
    similarity normalized to [0, 1].
    """

    def __init__(
        self,
        embedding_base_url: str = "http://localhost:8001",
        embedding_model: str = "nomic-embed-text",
        timeout: float = 60.0,
    ) -> None:
        self.embedding_base_url = embedding_base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.timeout = timeout

        logger.info(
            "AnswerRelevancyMetric initialized: url=%s, model=%s",
            self.embedding_base_url,
            self.embedding_model,
        )

    async def calculate_batch(
        self,
        questions: List[str],
        answers: List[str],
    ) -> List[RelevancyResult]:
        """Calculate answer relevancy for a batch of question/answer pairs.

        For each pair, computes cosine similarity between the question
        embedding and the answer embedding.  The raw similarity (range
        [-1, 1]) is normalized to [0, 1].

        Args:
            questions: List of question texts.
            answers: List of answer texts.

        Returns:
            List of :class:`RelevancyResult` with similarity scores.
        """
        results: List[RelevancyResult] = []

        for question, answer in zip(questions, answers):
            try:
                score = await self._calculate_single(question, answer)
                results.append(RelevancyResult(score=score))
            except Exception as exc:
                logger.error(
                    "Relevancy calculation failed for question '%.50s': %s",
                    question,
                    exc,
                )
                results.append(RelevancyResult(score=0.0))

        return results

    async def _calculate_single(
        self, question: str, answer: str,
    ) -> float:
        """Calculate relevancy for a single question/answer pair."""
        q_embedding = await self._get_embedding(question)
        a_embedding = await self._get_embedding(answer)

        if q_embedding is None or a_embedding is None:
            return 0.0

        similarity = self._cosine_similarity(q_embedding, a_embedding)
        # Normalize from [-1, 1] to [0, 1]
        return (similarity + 1.0) / 2.0

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding vector from the Embedding Proxy API."""
        url = f"{self.embedding_base_url}/v1/embeddings"
        payload = {
            "input": text,
            "model": self.embedding_model,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

            data = response.json()
            embedding = data["data"][0]["embedding"]
            return embedding

        except Exception as exc:
            logger.error("Failed to get embedding: %s", exc)
            return None

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors.

        Returns a value in [-1, 1].
        """
        a = np.array(vec_a)
        b = np.array(vec_b)

        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return float(np.dot(a, b) / (norm_a * norm_b))
