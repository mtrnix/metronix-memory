"""Workspace-scoped citation generator configuration storage."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.storage.citation_generator_config import (
    CitationGeneratorConfigStore,
    CitationGeneratorOverride,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def store():
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    yield CitationGeneratorConfigStore(engine)
    await engine.dispose()


async def test_config_is_workspace_scoped(store: CitationGeneratorConfigStore) -> None:
    await store.upsert(
        CitationGeneratorOverride(
            workspace_id="citation_config_ws_a",
            provider="ollama",
            model="qwen2.5:1.5b",
        )
    )

    selected = await store.get("citation_config_ws_a")

    assert selected is not None
    assert selected.model == "qwen2.5:1.5b"
    assert await store.get("citation_config_ws_b") is None


async def test_delete_is_idempotent(store: CitationGeneratorConfigStore) -> None:
    workspace_id = "citation_config_delete"
    await store.upsert(
        CitationGeneratorOverride(
            workspace_id=workspace_id,
            provider="ollama",
            model="qwen2.5:0.5b",
        )
    )

    assert await store.delete(workspace_id) is True
    assert await store.delete(workspace_id) is False
