"""Tests for BenchmarkGenerator — question generation via BenchmarkQED.

Tests:
- Generation with mocked BenchmarkQED
- Event loop isolation via asyncio.to_thread()
- Error handling (empty document list, QED error)
- Factory method from_settings()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.benchmarker.schemas.benchmark import QEDDocument
from metatron.benchmarker.services.generator import BenchmarkGenerator
from metatron.core.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_documents(count: int = 3) -> list[QEDDocument]:
    return [
        QEDDocument(
            source_id=f"src_{i}",
            title=f"Doc {i}",
            text=f"Content of document {i} with enough text for processing.",
            source_type="confluence",
            url=f"https://example.com/{i}",
        )
        for i in range(count)
    ]


def _make_settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        METATRON_SECRET_KEY="test",
        POSTGRES_HOST="localhost",
        POSTGRES_PASSWORD="test",
        FERNET_KEY="",
        DEEPSEEK_API_KEY="test-key",
        DEEPSEEK_MODEL="deepseek-chat",
        BENCHMARKER_EMBEDDING_PROXY_URL="http://localhost:8001",
        OLLAMA_EMBED_MODEL="nomic-embed-text",
    )


# ---------------------------------------------------------------------------
# Factory method
# ---------------------------------------------------------------------------


class TestFromSettings:
    def test_creates_generator_from_settings(self):
        settings = _make_settings()
        gen = BenchmarkGenerator.from_settings(settings)

        assert gen.deepseek_api_key == "test-key"
        assert gen.deepseek_model == "deepseek-chat"
        assert gen.embedding_base_url == "http://localhost:8001"
        assert gen.embedding_model_name == "nomic-embed-text"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_empty_documents_raises_value_error(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )

        with pytest.raises(ValueError, match="Document list cannot be empty"):
            await gen.generate_questions([], num_questions=5)

    @pytest.mark.asyncio
    async def test_zero_questions_raises_value_error(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        docs = _make_documents(3)

        with pytest.raises(ValueError, match="num_questions must be > 0"):
            await gen.generate_questions(docs, num_questions=0)

    @pytest.mark.asyncio
    async def test_negative_questions_raises_value_error(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        docs = _make_documents(3)

        with pytest.raises(ValueError, match="num_questions must be > 0"):
            await gen.generate_questions(docs, num_questions=-1)


# ---------------------------------------------------------------------------
# Generation with mocked QED
# ---------------------------------------------------------------------------


class TestGenerateQuestions:
    @pytest.mark.asyncio
    async def test_generate_calls_to_thread(self):
        """Verify that generate_questions uses asyncio.to_thread for isolation."""
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        docs = _make_documents(3)

        mock_questions = [
            MagicMock(
                id="q1",
                text="Question 1?",
                question_type="data_local",
                references=["ref1"],
                attributes=MagicMock(
                    model_dump=lambda: {
                        "input_question": "Q1?",
                        "reference_coverage": 0.5,
                        "relevant_reference_count": 1,
                        "reference_count": 2,
                        "min_reference_similarity": 0.1,
                        "max_reference_similarity": 0.9,
                        "mean_reference_similarity": 0.5,
                        "intra_inter_similarity_ratio": 1.0,
                        "claim_count": 0,
                    }
                ),
            )
        ]

        with patch("metatron.benchmarker.services.generator.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(return_value=mock_questions)
            mock_asyncio.new_event_loop = MagicMock()
            mock_asyncio.set_event_loop = MagicMock()

            result = await gen.generate_questions(docs, num_questions=5)

            mock_asyncio.to_thread.assert_awaited_once()
            assert result == mock_questions

    @pytest.mark.asyncio
    async def test_qed_error_propagates(self):
        """If BenchmarkQED fails inside the thread, the error propagates."""
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        docs = _make_documents(3)

        with patch("metatron.benchmarker.services.generator.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(side_effect=RuntimeError("QED failed"))

            with pytest.raises(RuntimeError, match="QED failed"):
                await gen.generate_questions(docs, num_questions=5)


# ---------------------------------------------------------------------------
# Text preparation
# ---------------------------------------------------------------------------


class TestTextPreparation:
    def test_prepare_text_units(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        docs = _make_documents(2)

        text_units = gen._prepare_text_units(docs)

        assert len(text_units) == 2
        assert text_units[0].id == "src_0"
        assert text_units[0].text == docs[0].text

    def test_source_metadata_stored(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        docs = _make_documents(1)

        gen._prepare_text_units(docs)

        assert "src_0" in gen.source_metadata
        assert gen.source_metadata["src_0"]["title"] == "Doc 0"


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_count_tokens_no_llm(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        assert gen.count_tokens_used() == 0

    def test_get_token_usage_details_no_llm(self):
        gen = BenchmarkGenerator(
            deepseek_api_key="key",
            embedding_api_key="key",
        )
        details = gen.get_token_usage_details()
        assert details["total_tokens"] == 0
