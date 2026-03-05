"""
Faithfulness metric — LLM as Judge.

Evaluates whether the RAG answer is grounded in (faithful to) the
provided context.  Uses DeepSeek API to judge if each statement in
the answer can be inferred from the context.
"""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass
from typing import List

import httpx

logger = structlog.get_logger()

FAITHFULNESS_PROMPT = """You are an impartial judge evaluating the faithfulness of an answer.

Faithfulness measures whether the answer is grounded in the provided context.
An answer is faithful if every claim it makes can be inferred from the context.

Question: {question}

Context:
{context}

Answer: {answer}

Evaluate the faithfulness of the answer on a scale from 0.0 to 1.0:
- 1.0: Every claim in the answer is fully supported by the context
- 0.5: Some claims are supported, others are not
- 0.0: The answer contains claims that contradict or are not found in the context

Respond in JSON format:
{{"score": <float 0.0-1.0>, "reasoning": "<brief explanation>"}}
"""


@dataclass
class FaithfulnessResult:
    """Result of the Faithfulness metric evaluation."""

    score: float
    reasoning: str


class FaithfulnessMetric:
    """Faithfulness evaluation using DeepSeek as LLM judge.

    Sends a prompt to DeepSeek asking it to evaluate whether the answer
    is grounded in the provided context.  Returns a score in [0, 1]
    and a reasoning string.
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
            "FaithfulnessMetric initialized: model=%s", deepseek_model,
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
    ) -> List[FaithfulnessResult]:
        """Calculate faithfulness for a batch of question/answer/context triples.

        Args:
            questions: List of question texts.
            answers: List of answer texts.
            contexts: List of context texts (concatenated chunks).

        Returns:
            List of :class:`FaithfulnessResult` with scores and reasoning.
        """
        results: List[FaithfulnessResult] = []

        for question, answer, context in zip(questions, answers, contexts):
            try:
                result = await self._evaluate_single(question, answer, context)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Faithfulness evaluation failed for question '%.50s': %s",
                    question,
                    exc,
                )
                results.append(FaithfulnessResult(score=0.0, reasoning=f"Error: {exc}"))

        return results

    async def _evaluate_single(
        self, question: str, answer: str, context: str,
    ) -> FaithfulnessResult:
        """Evaluate faithfulness for a single question/answer/context triple."""
        prompt = FAITHFULNESS_PROMPT.format(
            question=question,
            context=context,
            answer=answer,
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
    def _parse_response(response_data: dict) -> FaithfulnessResult:
        """Parse the LLM JSON response into a FaithfulnessResult."""
        score = float(response_data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        reasoning = str(response_data.get("reasoning", ""))
        return FaithfulnessResult(score=score, reasoning=reasoning)
