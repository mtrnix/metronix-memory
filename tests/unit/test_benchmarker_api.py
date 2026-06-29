"""Tests for Benchmarker API endpoints.

Tests request validation (422), correct responses (200),
error handling (404, 500), and all CRUD endpoints for
benchmarks and test runs.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from metronix.api.app import create_app
from metronix.benchmarker.db.models import (  # noqa: F401 — register models with Base
    BenchmarkQuestionRow,
    BenchmarkSetRow,
    TestResultRow,
    TestRunRow,
)
from metronix.core.config import Settings
from metronix.storage.pg_models import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _sqlite_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def _session_factory(_sqlite_engine):
    return sessionmaker(bind=_sqlite_engine, autocommit=False, autoflush=False)


@pytest.fixture()
def client(_session_factory) -> TestClient:
    """TestClient with patched get_session pointing to SQLite."""

    @contextmanager
    def _fake_get_session() -> Generator[Session, None, None]:
        session = _session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    settings = Settings(
        METRONIX_ENV="development",
        METRONIX_SECRET_KEY="test-key",
        POSTGRES_HOST="localhost",
        POSTGRES_PASSWORD="test",
        FERNET_KEY="",
    )

    with (
        patch("metronix.storage.pg_connection.get_session", _fake_get_session),
        patch("metronix.benchmarker.api.benchmarks.get_session", _fake_get_session),
        patch("metronix.benchmarker.api.test_runs.get_session", _fake_get_session),
        patch("metronix.benchmarker.api.generation.get_session", _fake_get_session),
        patch("metronix.benchmarker.api.testing.get_session", _fake_get_session),
    ):
        app = create_app(settings)
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_benchmark(client: TestClient, workspace_id: str = "ws1") -> dict:
    """Create a benchmark via API and return the response JSON."""
    resp = client.post(
        "/api/v1/benchmarker/benchmarks/",
        params={"workspace_id": workspace_id},
        json={
            "name": "Test Benchmark",
            "connection_id": "conn-1",
            "questions": [
                {
                    "text": "What is X?",
                    "question_type": "data_local",
                    "attributes": {
                        "input_question": "What is X?",
                        "reference_coverage": 0.5,
                        "relevant_reference_count": 1,
                        "reference_count": 2,
                        "min_reference_similarity": 0.1,
                        "max_reference_similarity": 0.9,
                        "mean_reference_similarity": 0.5,
                        "intra_inter_similarity_ratio": 1.0,
                        "claim_count": 0,
                    },
                }
            ],
            "tokens_used": 50,
        },
    )
    return resp


# ---------------------------------------------------------------------------
# Benchmark CRUD endpoints
# ---------------------------------------------------------------------------


class TestListBenchmarks:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/benchmarker/benchmarks/", params={"workspace_id": "ws1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["benchmarks"] == []

    def test_list_after_create(self, client):
        _create_benchmark(client)
        resp = client.get("/api/v1/benchmarker/benchmarks/", params={"workspace_id": "ws1"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_missing_workspace_id_422(self, client):
        resp = client.get("/api/v1/benchmarker/benchmarks/")
        assert resp.status_code == 422


class TestGetBenchmark:
    def test_get_existing(self, client):
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        resp = client.get(f"/api/v1/benchmarker/benchmarks/{bid}", params={"workspace_id": "ws1"})
        assert resp.status_code == 200
        assert resp.json()["benchmark"]["id"] == bid

    def test_get_nonexistent_404(self, client):
        resp = client.get("/api/v1/benchmarker/benchmarks/fake-id", params={"workspace_id": "ws1"})
        assert resp.status_code == 404

    def test_get_wrong_workspace_404(self, client):
        create_resp = _create_benchmark(client, workspace_id="ws1")
        bid = create_resp.json()["id"]

        resp = client.get(
            f"/api/v1/benchmarker/benchmarks/{bid}", params={"workspace_id": "ws_other"}
        )
        assert resp.status_code == 404


class TestCreateBenchmark:
    def test_create_success(self, client):
        resp = _create_benchmark(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "id" in data

    def test_create_empty_questions_422(self, client):
        resp = client.post(
            "/api/v1/benchmarker/benchmarks/",
            params={"workspace_id": "ws1"},
            json={
                "name": "Empty",
                "connection_id": "conn-1",
                "questions": [],
            },
        )
        assert resp.status_code == 422

    def test_create_missing_name_422(self, client):
        resp = client.post(
            "/api/v1/benchmarker/benchmarks/",
            params={"workspace_id": "ws1"},
            json={
                "connection_id": "conn-1",
                "questions": [{"text": "Q?", "question_type": "data_local", "attributes": {}}],
            },
        )
        assert resp.status_code == 422


class TestDeleteBenchmark:
    def test_delete_existing(self, client):
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/benchmarker/benchmarks/{bid}", params={"workspace_id": "ws1"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_nonexistent_404(self, client):
        resp = client.delete("/api/v1/benchmarker/benchmarks/fake", params={"workspace_id": "ws1"})
        assert resp.status_code == 404


class TestCloneBenchmark:
    def test_clone_success(self, client):
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/benchmarker/benchmarks/{bid}/clone", params={"workspace_id": "ws1"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] != bid
        assert data["question_count"] == 1

    def test_clone_nonexistent_404(self, client):
        resp = client.post(
            "/api/v1/benchmarker/benchmarks/fake/clone", params={"workspace_id": "ws1"}
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test runs CRUD endpoints
# ---------------------------------------------------------------------------


class TestListTestRuns:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/benchmarker/test-runs/", params={"workspace_id": "ws1"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_missing_workspace_422(self, client):
        resp = client.get("/api/v1/benchmarker/test-runs/")
        assert resp.status_code == 422


class TestSaveTestRun:
    def test_save_success(self, client):
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        resp = client.post(
            "/api/v1/benchmarker/test-runs/",
            json={
                "benchmark_set_id": bid,
                "name": "Run 1",
                "results": [
                    {
                        "actual_answer": "Answer",
                        "correctness": 0.8,
                        "confidence": 1.0,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total_tests"] == 1

    def test_save_empty_results_400(self, client):
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        resp = client.post(
            "/api/v1/benchmarker/test-runs/",
            json={
                "benchmark_set_id": bid,
                "name": "Empty",
                "results": [],
            },
        )
        assert resp.status_code == 400

    def test_save_nonexistent_benchmark_404(self, client):
        resp = client.post(
            "/api/v1/benchmarker/test-runs/",
            json={
                "benchmark_set_id": "fake-id",
                "name": "Run",
                "results": [{"actual_answer": "A"}],
            },
        )
        assert resp.status_code == 404


class TestGetTestRun:
    def test_get_existing(self, client):
        # Create benchmark + test run
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        run_resp = client.post(
            "/api/v1/benchmarker/test-runs/",
            json={
                "benchmark_set_id": bid,
                "name": "Run 1",
                "results": [{"actual_answer": "A", "correctness": 0.9}],
            },
        )
        run_id = run_resp.json()["test_run_id"]

        resp = client.get(
            f"/api/v1/benchmarker/test-runs/{run_id}", params={"workspace_id": "ws1"}
        )
        assert resp.status_code == 200
        assert resp.json()["test_run"]["id"] == run_id

    def test_get_nonexistent_404(self, client):
        resp = client.get("/api/v1/benchmarker/test-runs/fake", params={"workspace_id": "ws1"})
        assert resp.status_code == 404


class TestDeleteTestRun:
    def test_delete_existing(self, client):
        create_resp = _create_benchmark(client)
        bid = create_resp.json()["id"]

        run_resp = client.post(
            "/api/v1/benchmarker/test-runs/",
            json={
                "benchmark_set_id": bid,
                "name": "Run",
                "results": [{"actual_answer": "A"}],
            },
        )
        run_id = run_resp.json()["test_run_id"]

        resp = client.delete(
            f"/api/v1/benchmarker/test-runs/{run_id}", params={"workspace_id": "ws1"}
        )
        assert resp.status_code == 200

    def test_delete_nonexistent_404(self, client):
        resp = client.delete("/api/v1/benchmarker/test-runs/fake", params={"workspace_id": "ws1"})
        assert resp.status_code == 404
