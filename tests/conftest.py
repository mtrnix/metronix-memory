"""Shared test fixtures for unit tests.

Provides mock configurations and store stubs for testing
without requiring running services.
"""

from __future__ import annotations

import pytest

from metatron.core.config import Settings
from metatron.core.models import Chunk, ChunkType, Document, Skill, User, Role, Workspace


@pytest.fixture
def settings() -> Settings:
    """Test settings with safe defaults."""
    return Settings(
        METATRON_ENV="development",
        METATRON_SECRET_KEY="test-secret-key-for-unit-tests",
        POSTGRES_HOST="localhost",
        POSTGRES_PASSWORD="test",
        FERNET_KEY="",
    )


@pytest.fixture
def sample_document() -> Document:
    """A sample document for testing."""
    return Document(
        id="doc_001",
        workspace_id="ws_test",
        source_type="confluence",
        source_id="page_123",
        title="Getting Started Guide",
        content=(
            "Welcome to the platform. This guide covers initial setup and configuration. "
            "First, install the dependencies. Then configure your environment variables. "
            "After that, run the database migrations. Finally, start the development server. "
            "The platform supports multiple data sources including Confluence, Jira, and GitHub. "
            "Each data source requires its own set of credentials. "
            "You can manage connections through the API or the admin interface. "
            "For more information, see the architecture documentation."
        ),
        tags=["getting-started", "setup", "configuration"],
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Sample chunks for testing scoring and fusion."""
    return [
        Chunk(
            id="chunk_a",
            document_id="doc_001",
            workspace_id="ws_test",
            chunk_type=ChunkType.ROOT,
            content="Welcome to the platform overview.",
            token_count=6,
        ),
        Chunk(
            id="chunk_b",
            document_id="doc_001",
            workspace_id="ws_test",
            chunk_type=ChunkType.CHILD,
            parent_id="chunk_a",
            content="Install dependencies and configure environment.",
            token_count=6,
        ),
        Chunk(
            id="chunk_c",
            document_id="doc_002",
            workspace_id="ws_test",
            chunk_type=ChunkType.STANDALONE,
            content="Database migration guide and setup steps.",
            token_count=7,
        ),
    ]


@pytest.fixture
def sample_user() -> User:
    """A sample user for auth tests."""
    return User(
        id="user_001",
        username="testuser",
        email="test@example.com",
        role=Role.EDITOR,
        workspace_ids=["ws_test", "ws_other"],
    )


@pytest.fixture
def sample_skill() -> Skill:
    """A sample skill for engine tests."""
    return Skill(
        id="skill_001",
        name="knowledge_search",
        description="Search the knowledge base",
        content="# Knowledge Search\nSearch for answers.",
        tags=["search", "knowledge"],
        triggers=["search", "find"],
        enabled=True,
        builtin=True,
    )


@pytest.fixture
def sample_workspace() -> Workspace:
    """A sample workspace for testing."""
    return Workspace(
        id="ws_test",
        name="Test Workspace",
        slug="test-workspace",
    )
