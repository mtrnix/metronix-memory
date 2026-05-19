"""
Benchmark Generator using BenchmarkQED AutoQ.

Generates local and global questions with claims for RAG system testing.
Uses BenchmarkQED for data-local and data-global question generation.
All BenchmarkQED calls are isolated in asyncio.to_thread() to prevent
event loop conflicts with uvicorn.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from benchmark_qed.autod.data_model.text_unit import TextUnit
from benchmark_qed.autod.data_processor.embedding import TextEmbedder
from benchmark_qed.autod.sampler.clustering.kmeans import KmeansClustering
from benchmark_qed.autoq.data_model.question import Question as QEDQuestion
from benchmark_qed.autoq.question_gen.data_questions.global_question_gen import (
    DataGlobalQuestionGen,
)
from benchmark_qed.autoq.question_gen.data_questions.local_question_gen import (
    DataLocalQuestionGen,
)
from benchmark_qed.config.llm_config import LLMConfig, LLMProvider
from benchmark_qed.llm.provider.openai import OpenAIChat, OpenAIEmbedding

from metatron.benchmarker.schemas.benchmark import (
    BenchmarkQuestion,
    Claim,
    ClaimSource,
    QEDDocument,
    QuestionAttributes,
)

if TYPE_CHECKING:
    from metatron.core.config import Settings

logger = structlog.get_logger()

# Constants
MAX_TEXT_LENGTH = 2048  # Maximum text length for embeddings (Ollama nomic-embed-text limit)
MAX_EMBEDDING_RETRIES = 3  # Number of embedding creation attempts
GLOBAL_QUESTIONS_RATIO = 0.1  # Ratio of global questions (10%)


def _run_qed_in_thread(fn, *args, **kwargs):
    """Run an async BenchmarkQED function in a new event loop inside a thread.

    BenchmarkQED internally uses ``asyncio.get_event_loop()`` which conflicts
    with the already-running uvicorn loop.  This helper creates a fresh loop
    in the executor thread so the library works correctly.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(fn(*args, **kwargs))
    finally:
        loop.close()


class BenchmarkGenerator:
    """Question generator using BenchmarkQED AutoQ.

    Generates local (data-local) and global (data-global) questions with
    claims for RAG system benchmarking.  Automatically splits the total
    question count into local and global according to
    ``GLOBAL_QUESTIONS_RATIO`` (default 10 % global).
    """

    def __init__(
        self,
        deepseek_api_key: str,
        embedding_api_key: str,
        embedding_base_url: str = "http://localhost:8001",
        embedding_model: str = "nomic-embed-text",
        deepseek_base_url: str = "https://api.deepseek.com",
        deepseek_model: str = "deepseek-chat",
        num_questions: int = 5,
        oversample_factor: float = 2.0,
        concurrent_requests: int = 4,
        random_seed: int = 42,
        temperature: float = 0.0,
    ):
        """Initialise the benchmark generator.

        Args:
            deepseek_api_key: API key for DeepSeek.
            embedding_api_key: API key for the embedding service.
            embedding_base_url: Base URL for the embedding service.
            embedding_model: Embedding model name.
            deepseek_base_url: Base URL for DeepSeek.
            deepseek_model: DeepSeek model name.
            num_questions: Default number of questions to generate.
            oversample_factor: Oversampling factor for question generation.
            concurrent_requests: Number of concurrent requests.
            random_seed: Random seed for reproducibility.
            temperature: Temperature for LLM.
        """
        self.deepseek_api_key = deepseek_api_key
        self.embedding_api_key = embedding_api_key
        self.embedding_base_url = embedding_base_url
        self.embedding_model_name = embedding_model
        self.deepseek_base_url = deepseek_base_url
        self.deepseek_model = deepseek_model

        self.num_questions = num_questions
        self.oversample_factor = oversample_factor
        self.concurrent_requests = concurrent_requests
        self.random_seed = random_seed
        self.temperature = temperature

        # LLM parameters
        self.llm_params: dict[str, Any] = {
            "temperature": self.temperature,
            "seed": self.random_seed,
        }

        # Lazy-initialised models
        self.llm: OpenAIChat | None = None
        self.text_embedder: TextEmbedder | None = None
        self.embedding_model: OpenAIEmbedding | None = None

        # source_id → metadata mapping for enriching claim sources
        self.source_metadata: dict[str, dict[str, str]] = {}

        logger.info(
            "BenchmarkGenerator initialised: model=%s, num_questions=%d",
            deepseek_model,
            num_questions,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(cls, settings: Settings) -> BenchmarkGenerator:
        """Create a generator from Metatron Core settings.

        Maps ``Settings`` fields to constructor arguments:
        * ``deepseek_api_key`` from ``settings.deepseek_api_key``
        * ``embedding_base_url`` from ``settings.benchmarker_embedding_proxy_url``
        * ``embedding_api_key`` = ``"stub"`` (Embedding Proxy does not require a key)
        * ``deepseek_model`` from ``settings.deepseek_model``
        * ``embedding_model`` from ``settings.ollama_embed_model``
        """
        return cls(
            deepseek_api_key=settings.deepseek_api_key,
            embedding_api_key="stub",
            embedding_base_url=settings.benchmarker_embedding_proxy_url,
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model=settings.deepseek_model,
            embedding_model=settings.ollama_embed_model,
        )

    # ------------------------------------------------------------------
    # Internal helpers – model initialisation
    # ------------------------------------------------------------------

    def _create_llm_config(self) -> LLMConfig:
        """Create LLM configuration for DeepSeek."""
        return LLMConfig(
            provider=LLMProvider.OpenAIChat,
            model=self.deepseek_model,
            api_key=self.deepseek_api_key,
            concurrent_requests=self.concurrent_requests,
            init_args={"base_url": self.deepseek_base_url},
        )

    def _create_embedding_config(self) -> LLMConfig:
        """Create configuration for the embedding service."""
        return LLMConfig(
            provider=LLMProvider.OpenAIEmbedding,
            model=self.embedding_model_name,
            api_key=self.embedding_api_key,
            concurrent_requests=self.concurrent_requests,
            init_args={"base_url": self.embedding_base_url},
        )

    def _initialize_models(self) -> None:
        """Lazily initialise LLM and embedding models."""
        if self.llm is None:
            llm_config = self._create_llm_config()
            self.llm = OpenAIChat(llm_config)
            logger.info("DeepSeek LLM initialised")

        if self.text_embedder is None:
            embedding_config = self._create_embedding_config()
            self.embedding_model = OpenAIEmbedding(embedding_config)
            self.text_embedder = TextEmbedder(self.embedding_model)
            logger.info("Embedding service initialised")

    # ------------------------------------------------------------------
    # Internal helpers – text preparation
    # ------------------------------------------------------------------

    def _prepare_text_units(self, documents: list[QEDDocument]) -> list[TextUnit]:
        """Convert ``QEDDocument`` objects into ``TextUnit`` for BenchmarkQED.

        Also stores source metadata for later enrichment of claim sources.
        """
        text_units: list[TextUnit] = []

        for doc in documents:
            self.source_metadata[doc.source_id] = {
                "url": doc.url or "",
                "source_type": doc.source_type,
                "title": doc.title or "",
            }

            text_unit = TextUnit(
                id=doc.source_id,
                short_id=doc.source_id,
                text=doc.text,
                attributes={
                    "title": doc.title or "",
                    "source_type": doc.source_type,
                    "url": doc.url or "",
                },
            )
            text_units.append(text_unit)

        logger.info(
            "Prepared %d text units, saved metadata for %d sources",
            len(text_units),
            len(self.source_metadata),
        )
        return text_units

    def _validate_and_truncate_texts(self, text_units: list[TextUnit]) -> list[TextUnit]:
        """Validate and truncate texts to ``MAX_TEXT_LENGTH``.

        The embedding API has a limitation on input length.  Texts exceeding
        the limit are silently truncated.
        """
        truncated_count = 0

        for unit in text_units:
            if len(unit.text) > MAX_TEXT_LENGTH:
                logger.warning(
                    "Text %s too long (%d chars), truncating to %d",
                    unit.id,
                    len(unit.text),
                    MAX_TEXT_LENGTH,
                )
                unit.text = unit.text[:MAX_TEXT_LENGTH]
                truncated_count += 1

        if truncated_count > 0:
            logger.info("Truncated %d/%d texts", truncated_count, len(text_units))

        return text_units

    # ------------------------------------------------------------------
    # Internal helpers – embeddings & clustering
    # ------------------------------------------------------------------

    async def _create_embeddings_with_retry(self, text_units: list[TextUnit]) -> list[TextUnit]:
        """Create embeddings with retry and exponential backoff.

        Raises:
            Exception: If embedding creation fails after all attempts.
        """
        for attempt in range(MAX_EMBEDDING_RETRIES):
            try:
                text_units_with_embeddings = await self.text_embedder.embed_batch(
                    text_units, batch_size=1
                )

                valid_count = sum(
                    1 for unit in text_units_with_embeddings if unit.text_embedding is not None
                )

                if valid_count == 0:
                    raise ValueError("No embeddings created")

                logger.info("Created %d/%d embeddings", valid_count, len(text_units))
                return text_units_with_embeddings

            except Exception as e:
                if attempt < MAX_EMBEDDING_RETRIES - 1:
                    wait_time = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        "Attempt %d/%d failed: %s, retrying in %ds...",
                        attempt + 1,
                        MAX_EMBEDDING_RETRIES,
                        e,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "Failed to create embeddings after %d attempts",
                        MAX_EMBEDDING_RETRIES,
                    )
                    raise

        # Defensive — only reachable if MAX_EMBEDDING_RETRIES is non-positive,
        # which would also skip the loop body and any retry attempts.
        raise RuntimeError(
            f"_create_embeddings_with_retry: no attempts made "
            f"(MAX_EMBEDDING_RETRIES={MAX_EMBEDDING_RETRIES})"
        )

    async def _cluster_texts(
        self,
        text_units: list[TextUnit],
        num_clusters: int | None = None,
    ) -> list[TextUnit]:
        """Cluster text units for BenchmarkQED.

        Returns text units annotated with ``cluster_id``.
        """
        if num_clusters is None:
            num_clusters = min(5, len(text_units))

        logger.info(
            "Clustering %d texts into %d clusters",
            len(text_units),
            num_clusters,
        )

        text_units = self._validate_and_truncate_texts(text_units)

        logger.info("Creating embeddings...")
        text_units_with_embeddings = await self._create_embeddings_with_retry(text_units)

        logger.info("Performing clustering...")
        clustering = KmeansClustering(random_seed=self.random_seed)
        text_clusters = clustering.cluster(text_units_with_embeddings, num_clusters=num_clusters)

        all_texts: list[TextUnit] = []
        for cluster in text_clusters:
            for text_unit in cluster.text_units:
                text_unit.cluster_id = cluster.id
                all_texts.append(text_unit)

        logger.info(
            "Clustered %d texts into %d clusters",
            len(all_texts),
            len(text_clusters),
        )
        return all_texts

    # ------------------------------------------------------------------
    # Internal helpers – question conversion
    # ------------------------------------------------------------------

    def _convert_to_benchmark_question(self, qed_question: Any) -> BenchmarkQuestion:
        """Convert a BenchmarkQED question object into ``BenchmarkQuestion``.

        Handles both dict and object representations from BenchmarkQED.
        """
        if not isinstance(qed_question, dict):
            if hasattr(qed_question, "model_dump"):
                qed_question = qed_question.model_dump()
            elif hasattr(qed_question, "dict"):
                qed_question = qed_question.dict()
            elif hasattr(qed_question, "__dict__"):
                qed_question = qed_question.__dict__
            else:
                raise ValueError(f"Cannot serialise question of type {type(qed_question)}")

        # Convert claims
        claims: list[Claim] = []
        attributes_data = qed_question.get("attributes", {})

        for claim_data in attributes_data.get("claims", []):
            sources: list[ClaimSource] = []
            for src in claim_data.get("sources", []):
                source_id = src.get("source_id", "")
                claim_source = ClaimSource(
                    source_id=source_id,
                    text=src.get("text", ""),
                )
                # Enrich with stored metadata
                if source_id in self.source_metadata:
                    metadata = self.source_metadata[source_id]
                    claim_source.url = metadata.get("url")
                    claim_source.source_type = metadata.get("source_type")
                    claim_source.title = metadata.get("title")
                sources.append(claim_source)

            claim = Claim(
                statement=claim_data.get("statement", ""),
                sources=sources,
                score=claim_data.get("score", 0),
                source_ids=claim_data.get("source_ids", []),
            )
            claims.append(claim)

        # abstract_categories may be a string for global questions
        abstract_categories = attributes_data.get("abstract_categories", [])
        if isinstance(abstract_categories, str):
            abstract_categories = [abstract_categories]

        attributes = QuestionAttributes(
            input_question=attributes_data.get("input_question", ""),
            period=attributes_data.get("period"),
            location=attributes_data.get("location"),
            named_entities=attributes_data.get("named_entities", []),
            abstract_categories=abstract_categories,
            background_information=attributes_data.get("background_information"),
            reference_coverage=attributes_data.get("reference_coverage", 0.0),
            relevant_reference_count=attributes_data.get("relevant_reference_count", 0),
            reference_count=attributes_data.get("reference_count", 0),
            min_reference_similarity=attributes_data.get("min_reference_similarity", 0.0),
            max_reference_similarity=attributes_data.get("max_reference_similarity", 0.0),
            mean_reference_similarity=attributes_data.get("mean_reference_similarity", 0.0),
            intra_inter_similarity_ratio=attributes_data.get("intra_inter_similarity_ratio", 0.0),
            claim_count=attributes_data.get("claim_count", 0),
            claims=claims,
            is_representative=attributes_data.get("is_representative", True),
        )

        return BenchmarkQuestion(
            id=qed_question.get("id", ""),
            text=qed_question.get("text", ""),
            question_type=qed_question.get("question_type", "data_local"),
            references=qed_question.get("references", []),
            attributes=attributes,
        )

    def _convert_to_qed_question(self, benchmark_question: BenchmarkQuestion) -> QEDQuestion:
        """Convert ``BenchmarkQuestion`` back to BenchmarkQED format.

        Used for global question generation which requires local questions
        as input.
        """
        return QEDQuestion(
            id=benchmark_question.id,
            text=benchmark_question.text,
            references=benchmark_question.references,
            attributes={
                "abstract_categories": benchmark_question.attributes.abstract_categories or [],
                "named_entities": benchmark_question.attributes.named_entities or [],
            },
        )

    def _convert_questions_with_error_handling(
        self,
        qed_questions: list[Any],
        question_type: str,
    ) -> list[BenchmarkQuestion]:
        """Convert a list of QED questions, skipping any that fail."""
        converted: list[BenchmarkQuestion] = []

        for qed_question in qed_questions:
            try:
                bq = self._convert_to_benchmark_question(qed_question)
                bq.question_type = question_type
                converted.append(bq)
            except Exception as e:
                logger.error(
                    "Error converting %s question: %s",
                    question_type,
                    e,
                    exc_info=True,
                )
                continue

        return converted

    # ------------------------------------------------------------------
    # Internal helpers – question generation (run inside thread)
    # ------------------------------------------------------------------

    async def _generate_local_questions_async(
        self,
        text_units: list[TextUnit],
        num_questions: int,
    ) -> list[BenchmarkQuestion]:
        """Generate local (data-local) questions (async, runs inside thread)."""
        if num_questions <= 0:
            return []

        logger.info("Generating %d data-local questions...", num_questions)

        local_generator = DataLocalQuestionGen(
            llm=self.llm,
            llm_params=self.llm_params,
            text_embedder=self.text_embedder,
            text_units=text_units,
            concurrent_coroutines=self.concurrent_requests,
            random_seed=self.random_seed,
        )

        local_results = await local_generator.agenerate(
            num_questions=num_questions,
            oversample_factor=self.oversample_factor,
        )

        local_questions = self._convert_questions_with_error_handling(
            local_results.selected_questions, question_type="data_local"
        )

        logger.info("Generated %d local questions", len(local_questions))
        return local_questions

    async def _generate_global_questions_async(
        self,
        local_questions: list[BenchmarkQuestion],
        num_questions: int,
    ) -> list[BenchmarkQuestion]:
        """Generate global (data-global) questions (async, runs inside thread).

        Global questions require local questions as input and are generated
        based on the categories of local questions.
        """
        if num_questions <= 0:
            return []

        if not local_questions:
            logger.warning("No local questions available for global generation, skipping")
            return []

        logger.info("Generating %d data-global questions...", num_questions)

        local_qed_questions: list[QEDQuestion] = []
        category_stats: dict[str, int] = {}

        for bq in local_questions:
            abstract_categories = bq.attributes.abstract_categories or []
            for cat in abstract_categories:
                category_stats[cat] = category_stats.get(cat, 0) + 1

            if not abstract_categories:
                logger.warning("Question %s has no abstract_categories, skipping", bq.id)
                continue

            local_qed_questions.append(self._convert_to_qed_question(bq))

        self._log_category_statistics(category_stats)

        logger.info(
            "Prepared %d local questions with categories for global generation",
            len(local_qed_questions),
        )

        if len(local_qed_questions) < 2:
            logger.warning(
                "Not enough local questions with categories (need at least 2), "
                "skipping global questions"
            )
            return []

        try:
            global_generator = DataGlobalQuestionGen(
                llm=self.llm,
                text_embedder=self.text_embedder,
                local_questions=local_qed_questions,
                llm_params=self.llm_params,
                concurrent_coroutines=self.concurrent_requests,
                random_seed=self.random_seed,
            )

            global_results = await global_generator.agenerate(
                num_questions=num_questions,
                oversample_factor=self.oversample_factor,
            )

            global_questions = self._convert_questions_with_error_handling(
                global_results.selected_questions, question_type="data_global"
            )

            logger.info("Generated %d global questions", len(global_questions))
            return global_questions

        except Exception as e:
            logger.error("Error generating global questions: %s", e, exc_info=True)
            logger.warning("Continuing without global questions")
            return []

    def _log_category_statistics(self, category_stats: dict[str, int]) -> None:
        """Log statistics about question categories."""
        logger.info("=== CATEGORY STATISTICS ===")
        logger.info("Total unique categories: %d", len(category_stats))

        top_categories = sorted(category_stats.items(), key=lambda x: x[1], reverse=True)[:10]

        if top_categories:
            logger.info("Top-10 categories:")
            for cat, count in top_categories:
                logger.info("  '%s': %d questions", cat, count)

        valid_categories = {cat: count for cat, count in category_stats.items() if count > 1}
        logger.info(
            "Categories with >1 question (valid for global): %d",
            len(valid_categories),
        )
        logger.info("===========================")

    # ------------------------------------------------------------------
    # Core async method that runs QED inside a thread
    # ------------------------------------------------------------------

    async def _run_generation_pipeline(
        self,
        documents: list[QEDDocument],
        num_questions: int,
        num_clusters: int | None = None,
    ) -> list[BenchmarkQuestion]:
        """Full generation pipeline (embeddings → clustering → questions).

        This method is async and is meant to be called via
        ``asyncio.to_thread(_run_qed_in_thread, ...)``.
        """
        self._initialize_models()

        text_units = self._prepare_text_units(documents)
        text_units = await self._cluster_texts(text_units, num_clusters)

        num_global = int(num_questions * GLOBAL_QUESTIONS_RATIO)
        num_local = num_questions - num_global

        logger.info(
            "Total questions: %d (local: %d, global: %d)",
            num_questions,
            num_local,
            num_global,
        )

        local_questions = await self._generate_local_questions_async(text_units, num_local)
        global_questions = await self._generate_global_questions_async(local_questions, num_global)

        all_questions = local_questions + global_questions
        logger.info(
            "Total generated %d questions (local: %d, global: %d)",
            len(all_questions),
            len(local_questions),
            len(global_questions),
        )
        return all_questions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_questions(
        self,
        documents: list[QEDDocument],
        num_questions: int | None = None,
        num_clusters: int | None = None,
    ) -> list[BenchmarkQuestion]:
        """Generate benchmark questions from documents.

        BenchmarkQED calls are isolated in ``asyncio.to_thread()`` to avoid
        event loop conflicts with the running uvicorn server.

        Args:
            documents: Documents to generate questions from.
            num_questions: Total number of questions (uses default if *None*).
            num_clusters: Number of clusters (auto-determined if *None*).

        Returns:
            List of generated ``BenchmarkQuestion`` objects.

        Raises:
            ValueError: If *documents* is empty or *num_questions* <= 0.
        """
        if not documents:
            raise ValueError("Document list cannot be empty")

        if num_questions is None:
            num_questions = self.num_questions

        if num_questions <= 0:
            raise ValueError(f"num_questions must be > 0, got: {num_questions}")

        logger.info("Starting question generation for %d documents", len(documents))

        # Isolate the entire BenchmarkQED pipeline in a separate thread
        # with its own event loop to prevent conflicts with uvicorn.
        questions = await asyncio.to_thread(
            _run_qed_in_thread,
            self._run_generation_pipeline,
            documents,
            num_questions,
            num_clusters,
        )

        return questions

    # ------------------------------------------------------------------
    # Token usage helpers
    # ------------------------------------------------------------------

    def count_tokens_used(self) -> int:
        """Return total number of tokens used by the LLM."""
        if self.llm is None:
            return 0
        usage = self.llm.get_usage()
        return usage.get("total_tokens", 0)

    def get_token_usage_details(self) -> dict:
        """Return detailed token usage statistics."""
        if self.llm is None:
            return {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }

        llm_usage = self.llm.get_usage()

        embedding_usage: dict = {}
        if self.embedding_model:
            embedding_usage = self.embedding_model.get_usage()

        return {
            "llm_total_tokens": llm_usage.get("total_tokens", 0),
            "llm_prompt_tokens": llm_usage.get("prompt_tokens", 0),
            "llm_completion_tokens": llm_usage.get("completion_tokens", 0),
            "embedding_prompt_tokens": embedding_usage.get("prompt_tokens", 0),
        }

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return f"BenchmarkGenerator(model={self.deepseek_model}, questions={self.num_questions})"

    def __repr__(self) -> str:
        return (
            f"BenchmarkGenerator(model='{self.deepseek_model}', "
            f"num_questions={self.num_questions}, "
            f"temperature={self.temperature})"
        )
