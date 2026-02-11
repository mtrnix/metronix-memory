# Connectors

## Overview

Connectors are the data ingestion layer of Metatron. They fetch content from external sources (Confluence, Jira, GitHub, etc.) and deliver it to the indexing pipeline.

## How Connectors Work

All connectors implement the `ConnectorInterface` defined in `src/connectors/base.py`:

```python
class ConnectorInterface(ABC):
    @abstractmethod
    async def configure(self, config: Dict[str, Any]) -> None:
        """Validate and store connector configuration."""
        pass

    @abstractmethod
    async def fetch(self, since: Optional[datetime] = None) -> AsyncIterator[Document]:
        """Fetch documents from the source. Optionally fetch only changes since a timestamp."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify connectivity and credentials."""
        pass
```

### Connector Lifecycle

1. **Configuration**: Connector receives config dict with credentials and options
2. **Health Check**: Validates connectivity before first sync
3. **Fetch**: Streams documents as they're retrieved (memory-efficient)
4. **Incremental Sync**: Uses `since` parameter to fetch only new/updated content

## Supported Connectors

### Confluence

**Implementation**: `src/connectors/confluence.py`

**Required Config Keys**:
- `base_url`: Confluence instance URL (e.g., `https://yourcompany.atlassian.net`)
- `email`: User email for authentication
- `api_token`: Confluence API token

**Authentication**: HTTP Basic Auth (email + API token)

**What Gets Indexed**:
- Page title, body (converted from Confluence storage format to Markdown)
- Space key, page ID, parent page ID
- Creator, last modifier, created/updated timestamps
- Labels/tags
- Metadata: `source=confluence`, `space_key`, `page_id`, `url`

**Incremental Sync**: Queries Confluence API with `lastModified >= since` filter

### Jira

**Implementation**: `src/connectors/jira.py`

**Required Config Keys**:
- `base_url`: Jira instance URL
- `email`: User email
- `api_token`: Jira API token
- `project_keys` (optional): List of project keys to sync (syncs all if omitted)

**Authentication**: HTTP Basic Auth

**What Gets Indexed**:
- Issue key, summary, description
- Issue type, status, priority
- Reporter, assignee
- Comments (as separate indexed text)
- Custom fields (configurable)
- Metadata: `source=jira`, `issue_key`, `project_key`, `issue_type`, `url`

**Incremental Sync**: JQL query with `updated >= since`

### Notion

**Implementation**: `src/connectors/notion.py`

**Required Config Keys**:
- `api_token`: Notion integration token
- `database_ids` (optional): Specific databases to sync

**Authentication**: Bearer token

**What Gets Indexed**:
- Page title and all blocks (converted to Markdown)
- Database rows with properties
- Parent/child relationships
- Created/last edited timestamps
- Metadata: `source=notion`, `page_id`, `database_id`, `url`

**Incremental Sync**: Filters pages by `last_edited_time >= since`

### GitHub

**Implementation**: `src/connectors/github.py`

**Required Config Keys**:
- `access_token`: GitHub personal access token or GitHub App token
- `repos`: List of repositories in `owner/repo` format
- `include_issues`: Boolean (default: `true`)
- `include_prs`: Boolean (default: `true`)
- `include_discussions`: Boolean (default: `false`)

**Authentication**: Token-based (Personal Access Token or GitHub App)

**What Gets Indexed**:
- Issues: title, body, comments, labels, state
- Pull Requests: title, body, comments, review comments, files changed
- Discussions: title, body, comments (if enabled)
- Code files: README.md, documentation files (optional)
- Metadata: `source=github`, `repo`, `issue_number` or `pr_number`, `url`

**Incremental Sync**: Queries GitHub API with `updated:>=since` filter

### Google Drive

**Implementation**: `src/connectors/google_drive.py`

**Required Config Keys**:
- `credentials_json`: Service account credentials JSON string
- `folder_ids` (optional): Specific folder IDs to sync
- `file_types` (optional): MIME types to include (default: docs, sheets, slides, PDFs)

**Authentication**: OAuth 2.0 service account

**What Gets Indexed**:
- Google Docs: title, full text content (converted to Markdown)
- Google Sheets: title, sheet names, cell data (as tables)
- Google Slides: title, slide text
- PDFs: title, extracted text
- Metadata: `source=google_drive`, `file_id`, `mime_type`, `url`

**Incremental Sync**: Queries Drive API with `modifiedTime >= since`

### Slack History

**Implementation**: `src/connectors/slack.py`

**Required Config Keys**:
- `bot_token`: Slack bot user OAuth token (requires `channels:history`, `groups:history` scopes)
- `channel_ids` (optional): Specific channels to sync (syncs all accessible if omitted)
- `include_threads`: Boolean (default: `true`)

**Authentication**: OAuth 2.0 bot token

**What Gets Indexed**:
- Messages: text, user, timestamp
- Thread replies (if enabled)
- Channel name and context
- Files/attachments: title, description (content not indexed by default)
- Metadata: `source=slack`, `channel_id`, `message_ts`, `thread_ts`, `url`

**Incremental Sync**: Fetches messages with `oldest >= since` parameter

### Files (Local Filesystem)

**Implementation**: `src/connectors/files.py`

**Required Config Keys**:
- `paths`: List of absolute file or directory paths
- `extensions` (optional): File extensions to include (default: `.txt`, `.md`, `.pdf`, `.docx`)
- `recursive`: Boolean (default: `true`)

**Authentication**: None (uses filesystem permissions)

**What Gets Indexed**:
- Text files: full content
- Markdown: parsed and converted
- PDFs: extracted text
- Word docs: extracted text
- Metadata: `source=files`, `file_path`, `file_name`, `extension`, `size_bytes`

**Incremental Sync**: Checks file modification time against `since` timestamp

## Writing a New Connector

### Step 1: Implement ConnectorInterface

Create a new file in `src/connectors/`:

```python
from typing import AsyncIterator, Dict, Any, Optional
from datetime import datetime
from src.connectors.base import ConnectorInterface
from src.models.document import Document
import structlog

logger = structlog.get_logger()

class MyServiceConnector(ConnectorInterface):
    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self.client: Optional[MyServiceClient] = None

    async def configure(self, config: Dict[str, Any]) -> None:
        """Validate required config keys and initialize client."""
        required_keys = ["api_key", "base_url"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required config key: {key}")

        self.config = config
        self.client = MyServiceClient(
            api_key=config["api_key"],
            base_url=config["base_url"]
        )
        logger.info("my_service_connector_configured")

    async def fetch(self, since: Optional[datetime] = None) -> AsyncIterator[Document]:
        """Fetch documents from MyService."""
        if not self.client:
            raise RuntimeError("Connector not configured")

        async for item in self.client.get_items(modified_since=since):
            yield Document(
                id=item.id,
                content=item.text,
                metadata={
                    "source": "myservice",
                    "item_id": item.id,
                    "created_at": item.created_at.isoformat(),
                    "url": f"{self.config['base_url']}/items/{item.id}"
                }
            )

        logger.info("my_service_fetch_complete")

    async def health_check(self) -> bool:
        """Verify API connectivity."""
        if not self.client:
            return False

        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.error("my_service_health_check_failed", error=str(e))
            return False
```

### Step 2: Register in ConnectorRegistry

Add your connector to `src/connectors/registry.py`:

```python
from src.connectors.myservice import MyServiceConnector

class ConnectorRegistry:
    _connectors = {
        "confluence": ConfluenceConnector,
        "jira": JiraConnector,
        "notion": NotionConnector,
        "github": GitHubConnector,
        "google_drive": GoogleDriveConnector,
        "slack": SlackConnector,
        "files": FilesConnector,
        "myservice": MyServiceConnector,  # Add here
    }
```

### Step 3: Add Tests

Create `tests/unit/test_connector_myservice.py`:

```python
import pytest
from src.connectors.myservice import MyServiceConnector

@pytest.mark.asyncio
async def test_myservice_configure():
    connector = MyServiceConnector()
    await connector.configure({"api_key": "test", "base_url": "https://api.example.com"})
    assert connector.config["api_key"] == "test"

@pytest.mark.asyncio
async def test_myservice_health_check():
    connector = MyServiceConnector()
    await connector.configure({"api_key": "test", "base_url": "https://api.example.com"})
    # Mock client.ping() as needed
    result = await connector.health_check()
    assert result is True
```

## Incremental Sync

All connectors support incremental sync via the `since` parameter:

```python
# Initial sync (fetch everything)
async for doc in connector.fetch():
    await index_document(doc)

# Later: incremental sync (fetch only changes since last sync)
last_sync_time = await get_last_sync_time(connection_id)
async for doc in connector.fetch(since=last_sync_time):
    await index_document(doc)
```

The connector is responsible for:
- Converting `since` to the appropriate API filter
- Handling timezone conversions if needed
- Returning only documents modified after `since`

## Rate Limit Handling

Connectors should implement exponential backoff when rate limited:

```python
import asyncio
from typing import Optional

async def _make_request_with_retry(
    self,
    request_fn,
    max_retries: int = 5,
    base_delay: float = 1.0
) -> Any:
    """Make API request with exponential backoff on rate limit."""
    for attempt in range(max_retries):
        try:
            return await request_fn()
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise

            delay = base_delay * (2 ** attempt)
            logger.warning(
                "rate_limit_hit",
                attempt=attempt + 1,
                delay_seconds=delay
            )
            await asyncio.sleep(delay)

    raise RuntimeError("Max retries exceeded")
```

Use this pattern in your `fetch()` method when making API calls:

```python
async def fetch(self, since: Optional[datetime] = None) -> AsyncIterator[Document]:
    items = await self._make_request_with_retry(
        lambda: self.client.list_items(since=since)
    )
    for item in items:
        yield await self._item_to_document(item)
```

## Best Practices

1. **Stream Documents**: Use `AsyncIterator[Document]` to yield documents one at a time, not load all into memory
2. **Structured Logging**: Use structlog, never print()
3. **Type Hints**: Add type hints to all method signatures
4. **Error Handling**: Log errors with context, don't let exceptions crash the sync
5. **Metadata Consistency**: Always include `source`, `url`, and source-specific IDs
6. **Rate Limits**: Implement exponential backoff for all external API calls
7. **Async All The Way**: Use async/await for all I/O operations
8. **Configuration Validation**: Fail fast in `configure()` if required keys are missing
