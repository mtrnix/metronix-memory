# Contributing to Metatron Core

## Development Setup

### Prerequisites

- Python 3.12 or higher
- Docker and Docker Compose
- Make
- Git

### Initial Setup

1. Clone the repository:
```bash
git clone https://github.com/yourorg/metatron-core.git
cd metatron-core
```

2. Run the setup script:
```bash
make setup
```

This will:
- Create a Python virtual environment
- Install all dependencies (including dev dependencies)
- Install pre-commit hooks
- Set up the development database

3. Copy the environment file:
```bash
cp .env.example .env
```

Edit `.env` to configure local services:
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/metatron
QDRANT_URL=http://localhost:6333
MEMGRAPH_URL=bolt://localhost:7687
OLLAMA_URL=http://localhost:11434
```

4. Start services:
```bash
docker compose up -d
```

5. Run migrations:
```bash
make migrate
```

6. Verify setup:
```bash
make test
```

## Code Style

Metatron uses strict code style conventions enforced by automated tools.

### Linting and Formatting

We use `ruff` for both linting and formatting:

```bash
# Run linter
make lint

# Auto-fix issues
make format
```

### Ruff Configuration

Configuration is in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "ANN", # flake8-annotations
    "ASYNC", # flake8-async
    "S",   # flake8-bandit
    "B",   # flake8-bugbear
    "A",   # flake8-builtins
    "C4",  # flake8-comprehensions
    "T20", # flake8-print
    "SIM", # flake8-simplify
]

ignore = [
    "ANN101", # Missing type annotation for self
    "ANN102", # Missing type annotation for cls
]
```

### Type Checking

We use `mypy` for static type checking:

```bash
make typecheck
```

All code must pass type checking with no errors. Configuration is in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_generics = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
```

### Logging

- **NEVER use print()**: Always use `structlog`
- **Use structured logging**: Pass data as keyword arguments, not formatted strings

Good:
```python
import structlog

logger = structlog.get_logger()
logger.info("query_executed", duration_ms=450, results_count=15)
```

Bad:
```python
print(f"Query took {duration_ms}ms and returned {results_count} results")
logger.info(f"Query took {duration_ms}ms")
```

## Project Conventions

### Async Everywhere

All I/O operations must be async:

```python
# Good
async def fetch_data() -> List[str]:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

# Bad
def fetch_data() -> List[str]:
    response = requests.get(url)
    return response.json()
```

### Type Hints on Every Signature

All functions must have complete type annotations:

```python
# Good
async def process_document(
    doc_id: str,
    workspace_id: str,
    options: Optional[Dict[str, Any]] = None
) -> ProcessingResult:
    pass

# Bad
async def process_document(doc_id, workspace_id, options=None):
    pass
```

### Files Under 200 Lines

Keep files focused and under 200 lines. If a file grows beyond this:
- Split into multiple files
- Extract reusable logic into utilities
- Move constants/types to separate files

### Absolute Imports

Always use absolute imports, never relative:

```python
# Good
from src.models.document import Document
from src.connectors.base import ConnectorInterface

# Bad
from .models.document import Document
from ..connectors.base import ConnectorInterface
```

### Error Handling

Use structured error types from `src/errors/`:

```python
from src.errors.exceptions import ConnectorError, ValidationError

# Raise specific errors
if not config.get("api_key"):
    raise ValidationError("Missing required field: api_key")

# Catch and log
try:
    result = await connector.fetch()
except ConnectorError as e:
    logger.error("connector_fetch_failed", error=str(e), connector=connector.name)
    raise
```

## Pull Request Process

### 1. Create a Branch

Branch from `main`:

```bash
git checkout main
git pull origin main
git checkout -b feature/your-feature-name
```

Branch naming conventions:
- `feature/`: New features
- `fix/`: Bug fixes
- `refactor/`: Code refactoring
- `docs/`: Documentation changes
- `test/`: Test additions/changes

### 2. Make Changes

- Write code following the conventions above
- Add tests for new functionality
- Update documentation if needed
- Commit frequently with clear messages

Commit message format:
```
Short summary (50 chars or less)

Longer explanation if needed. Wrap at 72 characters.

- Bullet points are fine
- Use present tense: "Add feature" not "Added feature"
- Reference issues: "Fixes #123"
```

### 3. Ensure Tests Pass

Before opening a PR:

```bash
# Run all tests
make test

# Run linter
make lint

# Run type checker
make typecheck
```

All three must pass without errors.

### 4. Open a Pull Request

Push your branch:
```bash
git push origin feature/your-feature-name
```

Open a PR on GitHub with:
- Clear title describing the change
- Description explaining what and why
- Link to related issues
- Screenshots/examples if applicable

### 5. Code Review

- Address reviewer feedback
- Push additional commits (do not force-push during review)
- Ensure CI passes
- Get approval from at least one maintainer

### 6. Merge

Once approved and CI passes, a maintainer will merge your PR.

## Testing

### Test Structure

Tests are organized by type:

```
tests/
  unit/           # Unit tests (no external dependencies)
  integration/    # Integration tests (require docker compose)
  fixtures/       # Shared test fixtures
  conftest.py     # pytest configuration
```

Benchmarker tests are in `tests/unit/test_benchmarker_*.py` with shared fixtures in `tests/unit/conftest_benchmarker.py` (in-memory SQLite engine, mock connectors, mock external APIs).

### Writing Unit Tests

Unit tests should be fast and isolated:

```python
import pytest
from src.utils.chunking import chunk_text

@pytest.mark.asyncio
async def test_chunk_text_basic():
    text = "This is a test. This is another sentence."
    chunks = await chunk_text(text, chunk_size=20)

    assert len(chunks) == 2
    assert chunks[0].content == "This is a test."
    assert chunks[1].content == "This is another sentence."

@pytest.mark.asyncio
async def test_chunk_text_empty():
    chunks = await chunk_text("", chunk_size=100)
    assert len(chunks) == 0
```

### Writing Integration Tests

Integration tests require docker services:

```python
import pytest
from src.repositories.document_repository import DocumentRepository
from src.models.document import Document

@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_repository_create(db_session):
    """Test creating a document in the database."""
    repo = DocumentRepository(db_session)

    doc = Document(
        id="test-doc-1",
        content="Test content",
        workspace_id="test-workspace"
    )

    created = await repo.create(doc)
    assert created.id == doc.id

    # Verify it was persisted
    fetched = await repo.get_by_id(doc.id)
    assert fetched.content == "Test content"
```

Run integration tests:
```bash
docker compose up -d  # Start services
make test-integration
```

### Test Coverage

Aim for at least 80% code coverage:

```bash
make coverage
```

This generates a coverage report in `htmlcov/index.html`.

### Fixtures

Reusable fixtures are in `tests/conftest.py`:

```python
import pytest
from src.database import SessionLocal

@pytest.fixture
async def db_session():
    """Provide a database session for testing."""
    async with SessionLocal() as session:
        yield session
        await session.rollback()

@pytest.fixture
def sample_document():
    """Provide a sample document."""
    return Document(
        id="test-1",
        content="Test content",
        workspace_id="workspace-1"
    )
```

## Architecture Rules

### Layered Architecture

Metatron follows a layered architecture. Lower layers cannot import from upper layers:

```
API Layer (src/api/)
  |
Service Layer (src/services/)
  |
Repository Layer (src/repositories/)
  |
Model Layer (src/models/)
  |
Database Layer (src/database.py)
```

Rules:
- Repositories can import models and database, but not services or API
- Services can import repositories and models, but not API
- API can import services, repositories, and models

### Interfaces for Extension

Use abstract base classes for extensibility:

```python
from abc import ABC, abstractmethod

class ConnectorInterface(ABC):
    @abstractmethod
    async def fetch(self) -> AsyncIterator[Document]:
        pass

class ConfluenceConnector(ConnectorInterface):
    async def fetch(self) -> AsyncIterator[Document]:
        # Implementation
        pass
```

### Dependency Injection

Use dependency injection to decouple components:

```python
from typing import Protocol

class EmbeddingService(Protocol):
    async def embed(self, text: str) -> List[float]:
        ...

class QueryService:
    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service

    async def execute_query(self, query: str) -> List[Document]:
        embedding = await self.embedding_service.embed(query)
        # Use embedding...
```

This allows:
- Easy testing with mocks
- Swapping implementations without changing consumers
- Clear dependency graph

### Graceful Degradation

Wrap external calls with error handling:

```python
async def _safe_call(
    func,
    default_value,
    error_message: str
):
    """Execute a function with error handling and fallback."""
    try:
        return await func()
    except Exception as e:
        logger.warning(
            "safe_call_failed",
            error=str(e),
            message=error_message
        )
        return default_value

# Usage
graph_results = await _safe_call(
    lambda: fetch_related_chunks(chunk_ids),
    default_value=[],
    error_message="Graph enrichment failed, continuing without related chunks"
)
```

## Common Commands

```bash
# Development
make setup          # Initial setup
make run            # Run the server
make shell          # Open Python shell with context

# Testing
make test           # Run all tests
make test-unit      # Run unit tests only
make test-integration  # Run integration tests only
make coverage       # Generate coverage report

# Code Quality
make lint           # Run linter
make format         # Auto-format code
make typecheck      # Run type checker

# Database
make migrate        # Run migrations
make migration MSG="description"  # Create new migration
make db-reset       # Drop and recreate database

# Docker
make docker-build   # Build Docker image
make docker-up      # Start all services
make docker-down    # Stop all services
make docker-logs    # View logs
```

## Getting Help

- Check existing documentation in `docs/`
- Search for similar issues on GitHub
- Ask in the project's Slack/Discord channel
- Open a GitHub issue for bugs or feature requests

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on the code, not the person
- Assume good intentions
- Help newcomers learn and contribute

Thank you for contributing to Metatron Core.
