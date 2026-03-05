"""
Context Recall metric — LLM as Judge.

Evaluates whether the retrieved context contains all the information
needed to verify the ground truth claims.  Uses DeepSeek API to judge
if each ground truth claim can be attributed to the context.
"""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass
from typing import List

import httpx

logger = structlog.get_logger()

CONTEXT_RECALL_PROMPT = """You are an impartial judge evaluating context recall.

Context recall measures whether the retrieved context contains all the information
needed to verify the ground truth answer.

Question: {question}

Retrieved context:
{context}

Ground truth answer: {ground_truth}

RAG system answer: {answer}

Evaluate the context recall on a scale from 0.0 to 1.0:
- 1.0: The context contains all information needed to verify every claim in the ground truth
- 0.5: The context contains some but not all information needed
- 0.0: The context does not contain the information needed to verify the ground truth

Respond in JSON format:
{{"score": <float 0.0-1.0>, "reasoning": "<brief explanation>"}}
"""


@dataclass
class ContextRecallResult:
    """Result of the Context Recall metric evaluation."""

    score: float
    reasoning: str


class ContextRecallMetric:
    """Context recall evaluation using DeepSeek as LLM judge.

    Evaluates whether the retrieved context contains all the information
    needed to verify the ground truth claims from the benchmark question.
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
            "ContextRecallMetric initialized: model=%s", deepseek_model,
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
        answers: List[str],
        contexts: List[str],
        ground_truths: List[str],
    ) -> List[ContextRecallResult]:
        """Calculate context recall for a batch of questions.

        Args:
            questions: List of question texts.
            answers: List of RAG answer texts.
            contexts: List of context texts (concatenated chunks).
            ground_truths: List of ground truth texts (from claims).

        Returns:
            List of :class:`ContextRecallResult` with scores and reasoning.
        """
        results: List[ContextRecallResult] = []

        for question, answer, context, ground_truth in zip(
            questions, answers, contexts, ground_truths,
        ):
            try:
                result = await self._evaluate_single(
                    question, answer, context, ground_truth,
                )
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Context recall evaluation failed for question '%.50s': %s",
                    question,
                    exc,
                )
                results.append(
                    ContextRecallResult(score=0.0, reasoning=f"Error: {exc}"),
                )

        return results

    async def _evaluate_single(
        self,
        question: str,
        answer: str,
        context: str,
        ground_truth: str,
    ) -> ContextRecallResult:
        """Evaluate context recall for a single question."""
        prompt = CONTEXT_RECALL_PROMPT.format(
            question=question,
            answer=answer,
            context=context,
            ground_truth=ground_truth,
        )

        response_data = await self._call_deepseek(prompt)
        return self._parse_response(response_data)

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

    @staticmethod
    def _parse_response(response_data: dict) -> ContextRecallResult:
        """Parse the LLM JSON response into a ContextRecallResult."""
        score = float(response_data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        reasoning = str(response_data.get("reasoning", ""))
        return ContextRecallResult(score=score, reasoning=reasoning)
