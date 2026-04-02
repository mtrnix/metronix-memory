"""Tests for DocumentSampler — connector adapter for BenchmarkQED.

Validates:
- Property 1: sample size invariant — result contains min(N, L) documents
- Property 2: field mapping correctness — Document → QEDDocument
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.benchmarker.schemas.benchmark import QEDDocument
from metatron.benchmarker.services.document_sampler import DocumentSampler
from metatron.core.models import Connection, Document

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_documents(count: int) -> list[Document]:
    """Create a list of sample Documents."""
    return [
        Document(
            id=f"doc_{i}",
            workspace_id="ws_test",
            source_type="confluence",
            source_id=f"page_{i}",
            title=f"Document {i}",
            content=f"Content of document {i}",
            url=f"https://example.com/doc/{i}",
        )
        for i in range(count)
    ]


def _make_sampler(documents: list[Document]) -> tuple[DocumentSampler, AsyncMock]:
    """Create a DocumentSampler with a mocked connector returning *documents*."""
    connector = AsyncMock()
    connector.configure = AsyncMock()
    connector.fetch = AsyncMock(return_value=documents)

    registry = MagicMock()
    registry.create.return_value = connector

    return DocumentSampler(registry), connector


def _make_connection() -> Connection:
    return Connection(workspace_id="ws_test", connector_type="confluence")


# ---------------------------------------------------------------------------
# Property 1: Sample size invariant
# ---------------------------------------------------------------------------


class TestSampleSizeInvariant:
    """Result contains exactly min(N, len(docs)) documents."""

    @pytest.mark.asyncio
    async def test_n_less_than_docs(self):
        docs = _make_documents(10)
        sampler, _ = _make_sampler(docs)

        result = await sampler.sample_documents(
            _make_connection(),
            {},
            "ws_test",
            n=3,
        )

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_n_equals_docs(self):
        docs = _make_documents(5)
        sampler, _ = _make_sampler(docs)

        result = await sampler.sample_documents(
            _make_connection(),
            {},
            "ws_test",
            n=5,
        )

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_n_greater_than_docs(self):
        docs = _make_documents(3)
        sampler, _ = _make_sampler(docs)

        result = await sampler.sample_documents(
            _make_connection(),
            {},
            "ws_test",
            n=100,
        )

        assert len(result) == 3  # all available documents

    @pytest.mark.asyncio
    async def test_empty_document_list(self):
        sampler, _ = _make_sampler([])

        result = await sampler.sample_documents(
            _make_connection(),
            {},
            "ws_test",
            n=5,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_all_results_from_original_list(self):
        docs = _make_documents(10)
        sampler, _ = _make_sampler(docs)

        result = await sampler.sample_documents(
            _make_connection(),
            {},
            "ws_test",
            n=5,
        )

        original_ids = {d.source_id for d in docs}
        for qed_doc in result:
            assert qed_doc.source_id in original_ids


# ---------------------------------------------------------------------------
# Property 2: Field mapping correctness
# ---------------------------------------------------------------------------


class TestFieldMapping:
    """Document → QEDDocument field mapping is correct."""

    def test_to_qed_maps_fields_correctly(self):
        doc = Document(
            source_id="src_42",
            title="My Title",
            content="My Content",
            source_type="jira",
            url="https://jira.example.com/42",
        )

        qed = DocumentSampler._to_qed(doc)

        assert isinstance(qed, QEDDocument)
        assert qed.source_id == "src_42"
        assert qed.title == "My Title"
        assert qed.text == "My Content"  # content → text
        assert qed.source_type == "jira"
        assert qed.url == "https://jira.example.com/42"

    @pytest.mark.asyncio
    async def test_sampled_documents_have_correct_mapping(self):
        docs = _make_documents(2)
        sampler, _ = _make_sampler(docs)

        result = await sampler.sample_documents(
            _make_connection(),
            {},
            "ws_test",
            n=2,
        )

        for qed_doc in result:
            assert isinstance(qed_doc, QEDDocument)
            assert qed_doc.text != ""  # content mapped to text
            assert qed_doc.source_type == "confluence"


# ---------------------------------------------------------------------------
# Connector integration
# ---------------------------------------------------------------------------


class TestConnectorIntegration:
    """DocumentSampler correctly calls connector configure() and fetch()."""

    @pytest.mark.asyncio
    async def test_calls_configure_and_fetch(self):
        docs = _make_documents(3)
        sampler, connector = _make_sampler(docs)
        connection = _make_connection()
        config = {"url": "https://example.com", "api_token": "tok"}

        await sampler.sample_documents(connection, config, "ws_test", n=2)

        connector.configure.assert_awaited_once_with(connection, config)
        connector.fetch.assert_awaited_once_with("ws_test")

    @pytest.mark.asyncio
    async def test_registry_create_called_with_connector_type(self):
        docs = _make_documents(1)
        connector = AsyncMock()
        connector.configure = AsyncMock()
        connector.fetch = AsyncMock(return_value=docs)

        registry = MagicMock()
        registry.create.return_value = connector

        sampler = DocumentSampler(registry)
        connection = Connection(workspace_id="ws_test", connector_type="jira")

        await sampler.sample_documents(connection, {}, "ws_test", n=1)

        registry.create.assert_called_once_with("jira")
