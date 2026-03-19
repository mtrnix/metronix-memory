"""Tests for benchmarker API endpoints: /run-tests and /generate."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.benchmarker.api.generation import router as generation_router
from metatron.benchmarker.api.testing import router as testing_router
from metatron.benchmarker.schemas.benchmark import BenchmarkQuestion, QuestionAttributes


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    app.include_router(testing_router, prefix="/api/v1/benchmarker")
    app.include_router(generation_router, prefix="/api/v1/benchmarker")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_benchmark_set():
    """Mock benchmark set from database."""
    benchmark = MagicMock()
    benchmark.id = "bench1"
    benchmark.workspace_id = "ws1"
    benchmark.name = "Test Benchmark"
    benchmark.connection_id = "conn-1"
    return benchmark


@pytest.fixture
def mock_question_row():
    """Mock question row from database."""
    row = MagicMock()
    row.id = "q1"
    row.text = "What is the capital of France?"
    row.question_type = "data_local"
    row.references = ["ref1"]
    row.attributes = {
        "input_question": "What is the capital of France?",
        "claims": [
            {
                "statement": "Paris is the capital",
                "sources": [],
                "score": 1.0,
                "source_ids": [],
            }
        ],
        "named_entities": [],
        "abstract_categories": [],
    }
    return row


class TestRunTestsEndpoint:
    """Test POST /run-tests endpoint."""

    @pytest.mark.asyncio
    async def test_run_tests_success(
        self, client, mock_benchmark_set, mock_question_row
    ):
        """Test successful test run."""
        request_data = {
            "benchmark_set_id": "bench1",
            "workspace_id": "ws1",
            "name": "Test Run 1",
            "description": "Test description",
        }

        mock_test_run = MagicMock()
        mock_test_run.id = "run1"
        mock_test_run.benchmark_set_id = "bench1"
        mock_test_run.name = "Test Run 1"
        mock_test_run.description = "Test description"
        mock_test_run.total_tests = 1
        mock_test_run.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_test_run.avg_correctness = 0.8
        mock_test_run.avg_answer_relevancy = 0.9
        mock_test_run.avg_faithfulness = 0.85
        mock_test_run.avg_context_precision = 0.75
        mock_test_run.avg_context_recall = 0.7
        mock_test_run.avg_confidence = 0.95

        mock_test_result = MagicMock()
        mock_test_result.id = "result1"
        mock_test_result.question = {"text": "What is the capital of France?"}
        mock_test_result.actual_answer = "Paris"
        mock_test_result.correctness = 0.8
        mock_test_result.answer_relevancy = 0.9
        mock_test_result.faithfulness = 0.85
        mock_test_result.context_precision = 0.75
        mock_test_result.context_recall = 0.7
        mock_test_result.confidence = 0.95
        mock_test_result.claim_scores = []

        with patch("metatron.benchmarker.api.testing.get_session") as mock_session, \
             patch("metatron.benchmarker.api.testing.crud") as mock_crud, \
             patch("metatron.benchmarker.api.testing.ContextFetcher") as mock_fetcher_cls, \
             patch("metatron.benchmarker.api.testing.MetricsController") as mock_metrics_cls, \
             patch("metatron.benchmarker.api.testing.TestRunner") as mock_runner_cls, \
             patch("metatron.benchmarker.api.testing.get_settings") as mock_settings:

            # Setup mocks
            mock_session.return_value.__enter__.return_value.query.return_value.filter.return_value.first.return_value = mock_benchmark_set
            mock_crud.get_benchmark_set.return_value = mock_benchmark_set
            mock_crud.get_benchmark_questions.return_value = [mock_question_row]
            mock_crud.create_test_run.return_value = mock_test_run
            mock_crud.create_test_results.return_value = [mock_test_result]

            mock_runner = MagicMock()
            mock_runner.run_tests = AsyncMock(return_value={
                "contexts": [MagicMock(
                    question=BenchmarkQuestion(
                        id="q1",
                        text="What is the capital of France?",
                        question_type="data_local",
                        references=[],
                        attributes=QuestionAttributes(
                            input_question="What is the capital of France?",
                            reference_coverage=0.9,
                            relevant_reference_count=1,
                            reference_count=1,
                            min_reference_similarity=0.8,
                            max_reference_similarity=0.95,
                            mean_reference_similarity=0.9,
                            intra_inter_similarity_ratio=0.85,
                            claim_count=1,
                            claims=[],
                        ),
                    ),
                    answer="Paris",
                    to_dict=MagicMock(return_value={}),
                )],
                "metrics_results": [MagicMock(
                    correctness=0.8,
                    answer_relevancy=0.9,
                    faithfulness=0.85,
                    context_precision=0.75,
                    context_recall=0.7,
                    confidence=0.95,
                    claim_scores=[],
                )],
                "avg_metrics": {
                    "avg_correctness": 0.8,
                    "avg_answer_relevancy": 0.9,
                    "avg_faithfulness": 0.85,
                    "avg_context_precision": 0.75,
                    "avg_context_recall": 0.7,
                    "avg_confidence": 0.95,
                },
            })
            mock_runner_cls.return_value = mock_runner

            response = client.post(
                "/api/v1/benchmarker/run-tests",
                json=request_data,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "run1"
        assert data["name"] == "Test Run 1"
        assert data["total_tests"] == 1
        assert data["avg_correctness"] == 0.8

    def test_run_tests_benchmark_not_found(self, client):
        """Test with non-existent benchmark."""
        request_data = {
            "benchmark_set_id": "nonexistent",
            "workspace_id": "ws1",
            "name": "Test Run",
        }

        with patch("metatron.benchmarker.api.testing.get_session") as mock_session, \
             patch("metatron.benchmarker.api.testing.crud") as mock_crud, \
             patch("metatron.benchmarker.api.testing.get_settings"):

            mock_crud.get_benchmark_set.return_value = None

            response = client.post(
                "/api/v1/benchmarker/run-tests",
                json=request_data,
            )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_run_tests_no_questions(self, client, mock_benchmark_set):
        """Test with benchmark that has no questions."""
        request_data = {
            "benchmark_set_id": "bench1",
            "workspace_id": "ws1",
            "name": "Test Run",
        }

        with patch("metatron.benchmarker.api.testing.get_session") as mock_session, \
             patch("metatron.benchmarker.api.testing.crud") as mock_crud, \
             patch("metatron.benchmarker.api.testing.get_settings"):

            mock_crud.get_benchmark_set.return_value = mock_benchmark_set
            mock_crud.get_benchmark_questions.return_value = []

            response = client.post(
                "/api/v1/benchmarker/run-tests",
                json=request_data,
            )

        assert response.status_code == 400
        assert "no questions" in response.json()["detail"]


class TestGenerateEndpoint:
    """Test POST /generate endpoint."""

    @pytest.mark.asyncio
    async def test_generate_success(self, client):
        """Test successful benchmark generation."""
        request_data = {
            "workspace_id": "ws1",
            "connection_id": "conn1",
            "num_questions": 5,
            "num_clusters": 3,
        }

        mock_benchmark = MagicMock()
        mock_benchmark.id = "bench1"
        mock_benchmark.workspace_id = "ws1"
        mock_benchmark.name = "Generated (confluence)"
        mock_benchmark.connection_id = "conn1"
        mock_benchmark.description = "Auto-generated from confluence documents"
        mock_benchmark.tokens_used = 1000
        mock_benchmark.question_count = 5
        mock_benchmark.created_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_question = BenchmarkQuestion(
            id="q1",
            text="Test question?",
            question_type="data_local",
            references=[],
            attributes=QuestionAttributes(
                input_question="Test question?",
                reference_coverage=0.9,
                relevant_reference_count=1,
                reference_count=1,
                min_reference_similarity=0.8,
                max_reference_similarity=0.95,
                mean_reference_similarity=0.9,
                intra_inter_similarity_ratio=0.85,
                claim_count=0,
                claims=[],
            ),
        )

        mock_documents = [
            MagicMock(source_id="doc1", title="Doc 1", text="Content 1")
        ]

        mock_conn = {
            "id": "conn1",
            "workspace_id": "ws1",
            "connector_type": "confluence",
            "config": {"url": "http://confluence.com"},
        }

        with patch("metatron.benchmarker.api.generation.get_settings") as mock_settings, \
             patch("metatron.benchmarker.api.generation.PostgresStore") as mock_store_cls, \
             patch("metatron.benchmarker.api.generation.ConnectorRegistry") as mock_registry_cls, \
             patch("metatron.benchmarker.api.generation.register_builtins"), \
             patch("metatron.benchmarker.api.generation.DocumentSampler") as mock_sampler_cls, \
             patch("metatron.benchmarker.api.generation.BenchmarkGenerator") as mock_generator_cls, \
             patch("metatron.benchmarker.api.generation.get_session"), \
             patch("metatron.benchmarker.api.generation.crud") as mock_crud:

            # Setup mocks
            mock_settings_inst = mock_settings.return_value
            mock_settings_inst.fernet_key = "test-fernet-key"
            mock_settings_inst.postgres_dsn = "postgresql+asyncpg://localhost/test"

            mock_store = MagicMock()
            mock_store.get_connection_decrypted = AsyncMock(return_value=mock_conn)
            mock_store.close = AsyncMock()
            mock_store_cls.return_value = mock_store

            mock_sampler = MagicMock()
            mock_sampler.sample_documents = AsyncMock(return_value=mock_documents)
            mock_sampler_cls.return_value = mock_sampler

            mock_generator = MagicMock()
            mock_generator.generate_questions = AsyncMock(return_value=[mock_question])
            mock_generator.count_tokens_used.return_value = 1000
            mock_generator_cls.from_settings.return_value = mock_generator

            mock_crud.create_benchmark_set.return_value = mock_benchmark
            mock_crud.create_benchmark_questions.return_value = []

            response = client.post(
                "/api/v1/benchmarker/generate",
                json=request_data,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "bench1"
        assert data["connection_id"] == "conn1"
        assert data["question_count"] == 5
        assert data["tokens_used"] == 1000

    def test_generate_no_connection_id(self, client):
        """Test with missing connection_id."""
        request_data = {
            "workspace_id": "ws1",
            "num_questions": 5,
        }

        with patch("metatron.benchmarker.api.generation.get_settings") as mock_settings:
            mock_settings_inst = mock_settings.return_value
            mock_settings_inst.fernet_key = "test-fernet-key"

            response = client.post(
                "/api/v1/benchmarker/generate",
                json=request_data,
            )

        assert response.status_code == 422

    def test_generate_connection_not_found(self, client):
        """Test with non-existent connection."""
        request_data = {
            "workspace_id": "ws1",
            "connection_id": "nonexistent",
            "num_questions": 5,
        }

        with patch("metatron.benchmarker.api.generation.get_settings") as mock_settings, \
             patch("metatron.benchmarker.api.generation.PostgresStore") as mock_store_cls:

            mock_settings_inst = mock_settings.return_value
            mock_settings_inst.fernet_key = "test-fernet-key"
            mock_settings_inst.postgres_dsn = "postgresql+asyncpg://localhost/test"

            mock_store = MagicMock()
            mock_store.get_connection_decrypted = AsyncMock(return_value=None)
            mock_store.close = AsyncMock()
            mock_store_cls.return_value = mock_store

            response = client.post(
                "/api/v1/benchmarker/generate",
                json=request_data,
            )

        assert response.status_code == 404

    def test_generate_no_documents(self, client):
        """Test when no documents are found."""
        request_data = {
            "workspace_id": "ws1",
            "connection_id": "conn1",
            "num_questions": 5,
        }

        mock_conn = {
            "id": "conn1",
            "workspace_id": "ws1",
            "connector_type": "confluence",
            "config": {"url": "http://confluence.com"},
        }

        with patch("metatron.benchmarker.api.generation.get_settings") as mock_settings, \
             patch("metatron.benchmarker.api.generation.PostgresStore") as mock_store_cls, \
             patch("metatron.benchmarker.api.generation.ConnectorRegistry"), \
             patch("metatron.benchmarker.api.generation.register_builtins"), \
             patch("metatron.benchmarker.api.generation.DocumentSampler") as mock_sampler_cls:

            mock_settings_inst = mock_settings.return_value
            mock_settings_inst.fernet_key = "test-fernet-key"
            mock_settings_inst.postgres_dsn = "postgresql+asyncpg://localhost/test"

            mock_store = MagicMock()
            mock_store.get_connection_decrypted = AsyncMock(return_value=mock_conn)
            mock_store.close = AsyncMock()
            mock_store_cls.return_value = mock_store

            mock_sampler = MagicMock()
            mock_sampler.sample_documents = AsyncMock(return_value=[])
            mock_sampler_cls.return_value = mock_sampler

            response = client.post(
                "/api/v1/benchmarker/generate",
                json=request_data,
            )

        assert response.status_code == 400
        assert "No documents" in response.json()["detail"]


