"""
Correctness metric via BenchmarkQED AutoE (assertion scores).

Evaluates how correctly the RAG system answered each question by checking
generated claims against the actual answer.  Uses ``benchmark_qed.autoe``
for assertion scoring.

All BenchmarkQED calls are isolated in ``asyncio.to_thread()`` with a
fresh event loop to prevent conflicts with the running uvicorn loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

import pandas as pd
from benchmark_qed.autoe.assertion_scores import get_assertion_scores
from benchmark_qed.config.llm_config import LLMConfig, LLMProvider
from benchmark_qed.llm.provider.openai import OpenAIChat

from metatron.benchmarker.schemas.benchmark import BenchmarkQuestion

logger = logging.getLogger(__name__)


class QEDMetricsCalculator:
    """Correctness metric calculator using BenchmarkQED AutoE.

    Evaluates assertion scores for each question/answer pair by comparing
    the actual answer against the claims defined in the benchmark question.

    Mirrors the original metatron-benchmarker implementation: builds two
    DataFrames (answers + assertions) and calls ``get_assertion_scores``
    with keyword arguments.
    """

    def __init__(
        self,
        deepseek_api_key: str,
        deepseek_model: str = "deepseek-chat",
        deepseek_base_url: str = "https://api.deepseek.com",
        concurrent_requests: int = 4,
        temperature: float = 0.0,
    ) -> None:
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_model = deepseek_model
        self.deepseek_base_url = deepseek_base_url
        self.concurrent_requests = concurrent_requests
        self.temperature = temperature

        self._llm: Optional[OpenAIChat] = None
        self._llm_config: Optional[LLMConfig] = None

        logger.info(
            "QEDMetricsCalculator initialized: model=%s", deepseek_model,
        )

    def _initialize_llm(self) -> None:
        """Lazily initialize the LLM client and config."""
        if self._llm is None:
            self._llm_config = LLMConfig(
                provider=LLMProvider.OpenAIChat,
                model=self.deepseek_model,
                api_key=self.deepseek_api_key,
                concurrent_requests=self.concurrent_requests,
                init_args={"base_url": self.deepseek_base_url},
            )
            self._llm = OpenAIChat(self._llm_config)
            logger.info("QED LLM initialized for AutoE")

    def _prepare_dataframes(
        self,
        questions: List[BenchmarkQuestion],
        actual_answers: List[str],
    ) -> tuple:
        """Prepare answers and assertions DataFrames for AutoE.

        Returns:
            Tuple of (answers_df, assertions_df).
        """
        answers_data = []
        for question, answer in zip(questions, actual_answers):
            answers_data.append({
                "question_id": question.id,
                "question_text": question.text,
                "answer": answer,
            })
        answers_df = pd.DataFrame(answers_data)

        assertions_data = []
        for question in questions:
            claims = question.attributes.claims if question.attributes else []
            for idx, claim in enumerate(claims):
                assertions_data.append({
                    "question_id": question.id,
                    "question_text": question.text,
                    "assertion_id": f"{question.id}_claim_{idx}",
                    "assertion": claim.statement,
                })
        assertions_df = pd.DataFrame(assertions_data)

        logger.info(
            "Prepared DataFrames: %d answers, %d assertions",
            len(answers_df),
            len(assertions_df),
        )
        return answers_df, assertions_df

    async def evaluate_answers(
        self,
        questions: List[BenchmarkQuestion],
        actual_answers: List[str],
        latencies_ms: List[float],
    ) -> List[Dict]:
        """Evaluate correctness of answers using BenchmarkQED AutoE.

        Builds two DataFrames (answers + assertions) and calls
        ``get_assertion_scores`` with keyword arguments, matching the
        original metatron-benchmarker implementation.

        Args:
            questions: Benchmark questions with claims in attributes.
            actual_answers: Actual answers from the RAG system.
            latencies_ms: Latency measurements (not used in scoring,
                kept for API compatibility).

        Returns:
            List of dicts, each with keys:
            - ``score`` (float, 0-100): overall correctness percentage
            - ``claim_scores`` (list of dicts): per-claim results with
              assertion, score, passed, reasoning
        """
        self._initialize_llm()
        answers_df, assertions_df = self._prepare_dataframes(questions, actual_answers)

        if len(assertions_df) == 0:
            logger.warning("No assertions to evaluate")
            return [{"score": 0.0, "claim_scores": []} for _ in questions]

        try:
            results_df = await asyncio.to_thread(
                self._run_qed_sync,
                answers_df,
                assertions_df,
            )
        except Exception as exc:
            logger.error("get_assertion_scores failed: %s", exc)
            return [{"score": 0.0, "claim_scores": []} for _ in questions]

        return self._build_results(questions, results_df)

    def _run_qed_sync(
        self,
        answers_df: pd.DataFrame,
        assertions_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run get_assertion_scores synchronously in a thread.

        Applies nest_asyncio and creates a fresh event loop to avoid
        conflicts with the running uvicorn loop.
        """
        import nest_asyncio

        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        nest_asyncio.apply(loop)

        try:
            return get_assertion_scores(
                llm_client=self._llm,
                llm_config=self._llm_config,
                answers=answers_df,
                assertions=assertions_df,
                trials=1,
                question_id_key="question_id",
                question_text_key="question_text",
                answer_text_key="answer",
            )
        finally:
            loop.close()

    def _build_results(
        self,
        questions: List[BenchmarkQuestion],
        results_df: pd.DataFrame,
    ) -> List[Dict]:
        """Build per-question result dicts from the AutoE results DataFrame."""
        # Map question_text -> question_id
        question_text_to_id = {q.text: q.id for q in questions}

        # Group results by question
        results_by_question: Dict[str, List[Dict]] = {}
        for _, row in results_df.iterrows():
            question_text = row.get("question", "")
            question_id = question_text_to_id.get(question_text)
            if question_id is None:
                logger.warning(
                    "Question ID not found for question: %.50s...", question_text,
                )
                continue

            if question_id not in results_by_question:
                results_by_question[question_id] = []

            score_val = float(row.get("score", 0.0))
            results_by_question[question_id].append({
                "assertion": row.get("assertion", ""),
                "score": score_val,
                "passed": score_val > 0,
                "reasoning": row.get("reasoning", ""),
            })

        # Build final results list
        results: List[Dict] = []
        for question in questions:
            claim_scores = results_by_question.get(question.id, [])
            if claim_scores:
                passed_count = sum(1 for cs in claim_scores if cs["passed"])
                score = (passed_count / len(claim_scores)) * 100.0
            else:
                score = 0.0
            results.append({"score": score, "claim_scores": claim_scores})

        return results

