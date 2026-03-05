"""
Context Precision metric — LLM as Judge.

Evaluates the relevance of each retrieved context chunk to the question.
Uses DeepSeek API to judge whether each chunk is relevant, then computes
an overall precision score.
"""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass, field
from typing import List

import httpx

logger = structlog.get_logger()

CONTEXT_PRECISION_PROMPT = """You are an impartial judge evaluating the relevance of a context chunk to a question.

Question: {question}

Context chunk:
{chunk}

Is this context chunk relevant to answering the question?
Evaluate relevance on a scale from 0.0 to 1.0:
- 1.0: The chunk is highly relevant and directly helps answer the question
- 0.5: The chunk is partially relevant
- 0.0: The chunk is not relevant to the question at all

Respond in JSON format:
{{"score": <float 0.0-1.0>}}
"""


@dataclass
class ContextPrecisionResult:
    """Result of the Context Precision metric evaluation."""

    score: float
    chunk_scores: List[float] = field(default_factory=list)


class ContextPrecisionMetric:
    """Context precision evaluation using DeepSeek as LLM judge.

    For each question, evaluates the relevance of every retrieved chunk
    and computes the average relevance score as the precision metric.
    """

    def __init__(
        self,
        deepseek_api_key: str,
        deepseek_model: str = "deepseek-chat",
        deepseek_base_url: str = "https://api.deepseek.com",
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_model = deepseek_model
        self.deepseek_base_url = deepseek_base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

        logger.info(
            "ContextPrecisionMetric initialized: model=%s", deepseek_model,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create a reusable httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )
        return self._client

    async def calculate_batch(
        self,
        questions: List[str],
        chunks_per_question: List[List[str]],
    ) -> List[ContextPrecisionResult]:
        """Calculate context precision for a batch of questions.

        Args:
            questions: List of question texts.
            chunks_per_question: For each question, a list of chunk texts.

        Returns:
            List of :class:`ContextPrecisionResult` with scores and per-chunk scores.
        """
        results: List[ContextPrecisionResult] = []

        for question, chunks in zip(questions, chunks_per_question):
            try:
                result = await self._evaluate_single(question, chunks)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Context precision evaluation failed for question '%.50s': %s",
                    question,
                    exc,
                )
                results.append(ContextPrecisionResult(score=0.0, chunk_scores=[]))

        return results

    async def _evaluate_single(
        self, question: str, chunks: List[str],
    ) -> ContextPrecisionResult:
        """Evaluate context precision for a single question and its chunks."""
        if not chunks:
            return ContextPrecisionResult(score=0.0, chunk_scores=[])

        chunk_scores: List[float] = []
        for chunk in chunks:
            score = await self._evaluate_chunk(question, chunk)
            chunk_scores.append(score)

        avg_score = sum(chunk_scores) / len(chunk_scores) if chunk_scores else 0.0
        return ContextPrecisionResult(score=avg_score, chunk_scores=chunk_scores)

    async def _evaluate_chunk(self, question: str, chunk: str) -> float:
        """Evaluate relevance of a single chunk to the question."""
        prompt = CONTEXT_PRECISION_PROMPT.format(
            question=question,
            chunk=chunk,
        )

        try:
            response_data = await self._call_deepseek(prompt)
            score = float(response_data.get("score", 0.0))
            return max(0.0, min(1.0, score))
        except Exception as exc:
            logger.error("Failed to evaluate chunk relevance: %s", exc)
            return 0.0

    async def _call_deepseek(self, prompt: str) -> dict:
        """Call DeepSeek API with retry logic and a reusable client."""
        import asyncio as _asyncio

        url = f"{self.deepseek_base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.deepseek_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

        client = self._get_client()
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    "DeepSeek call failed (attempt %d/%d): %s, retrying in %ds",
                    attempt + 1, self.max_retries, exc, wait,
                )
                await _asyncio.sleep(wait)

        raise last_exc  # type: ignore[misc]
