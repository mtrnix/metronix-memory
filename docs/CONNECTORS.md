# Connectors

## Overview

Connectors are the data ingestion layer of Metronix. They fetch content from external sources (Confluence, Jira, GitHub, etc.) and deliver it to the indexing pipeline.

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

**Setup — form fields & how to get the token:**

Form fields (KB Admin → Sources → Add → Confluence):

- **Confluence URL** — your instance base URL, e.g. `https://yourcompany.atlassian.net`.
- **Username/Email** — the email you log into Atlassian with.
- **API Token** *(secret)* — see below.
- **Space Key** *(optional)* — the short key in a space's URL (`…/wiki/spaces/`**`ENG`**`/…`). Leave empty to sync **all** spaces.

Get the API token (Atlassian Cloud):

1. Go to **id.atlassian.com → Security → Create and manage API tokens** (`https://id.atlassian.com/manage-profile/security/api-tokens`).
2. **Create API token**, give it a label, **Copy** the value (shown once).
3. Paste it into **API Token**; use your account email in **Username/Email**.

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
- `url`: Jira instance URL (e.g., `https://yourcompany.atlassian.net`)
- `email`: User email
- `api_token`: Jira API token
- `project_keys` (optional): List of project keys to sync (syncs all if omitted)

**Authentication**: HTTP Basic Auth

**Setup — form fields & how to get the token:**

Form fields (KB Admin → Sources → Add → Jira):

- **Jira URL** — instance base URL, e.g. `https://yourcompany.atlassian.net`.
- **Username/Email** — your Atlassian login email.
- **API Token** *(secret)* — same Atlassian token as Confluence (one token works for both).
- **Project Key** *(optional)* — the prefix on issue keys, e.g. `PROJ` in `PROJ-123`. Leave empty to sync **all** projects.

Get the API token: same steps as Confluence — **id.atlassian.com → Security → Create and manage API tokens** → Create → Copy. If you already made one for Confluence, reuse it.

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

**Authentication**: Bearer token

**Setup — form fields & how to get the token:**

Form field (KB Admin → Sources → Add → Notion):

- **Integration Token** *(secret)* — an internal integration secret, starts with `ntn_` (older ones start with `secret_`).

Get the token:

1. Go to **notion.so/my-integrations** → **New integration** → type **Internal** → pick the workspace → **Submit**.
2. Copy the **Internal Integration Secret** into **Integration Token**.
3. **Important — share pages with the integration**, or it sees nothing: open each page/database → **•••** menu → **Connections** (Add connections) → select your integration. Sharing a parent page also grants its children.

**What Gets Indexed**:
- Page title and all blocks (recursively converted to Markdown)
- Child page and child database titles (content fetched as separate pages)
- Created/last edited timestamps
- Created by and last edited by (display name with fallback to user ID)
- Metadata: `source=notion`, `page_id`, `type`, `last_edited_time`, `created_by`, `last_edited_by`

**Incremental Sync**: Filters pages by `last_edited_time >= since` via search API sort + comparison

**Rate Limiting**: Handles HTTP 429 with 4-second retry delay

**Block Recursion**: Nested blocks are fetched up to 5 levels deep

### GitHub

**Implementation**: `src/metronix/connectors/github.py` (formatting in `github_processing.py`)

**Required Config Keys**:
- `token`: GitHub personal access token (required)
- `org`: organization / owner (optional)
- `repos`: comma-separated `repo` or `owner/repo` names, or empty / `*` for all accessible repos (optional)
- `base_url`: GitHub Enterprise Server API base, e.g. `https://ghe.example.com/api/v3` (optional)

**Authentication**: Personal access token (classic or fine-grained), read access to the target repositories.

**Setup — form fields & how to get the token:**

Form fields (KB Admin → Sources → Add → GitHub):

- **Personal Access Token** *(secret)* — see below.
- **Organization** *(optional)* — the owner (user or org), e.g. `mtrnix`. Lets you type bare repo names below.
- **Repositories** *(optional)* — comma-separated `repo1,repo2` (with Organization set) or full `owner/repo`. Leave empty or `*` for **all** repos the token can see.
- **Enterprise API URL** *(optional)* — only for **GitHub Enterprise Server**, e.g. `https://ghe.example.com/api/v3`. Leave empty for github.com.

Get the token:

1. GitHub → **Settings → Developer settings → Personal access tokens**.
2. **Fine-grained** (recommended): **Generate new token** → pick the repositories → under *Repository permissions* grant **Contents: Read-only** (and **Issues**/**Pull requests: Read-only** if you want those indexed) → generate → copy.
   *Classic alternative:* generate a token with the **`repo`** scope (or **`public_repo`** for public repos only).
3. Paste into **Personal Access Token**.

**What Gets Indexed**:
- README and Markdown (`.md`) files from the default branch
- Issues and pull requests (with comments; PRs also include review comments)
- Releases
- Metadata: `type=github`, `github_type` (`doc` / `issue` / `pull_request` / `release`), `repo`, `number`, `state`, `author`

**Incremental Sync**: Issues and PRs are filtered by their `updated` timestamp (`since`); files and releases are refetched each sync.

### Google Drive

**Implementation**: `src/metronix/connectors/gdrive.py` (formatting in `gdrive_processing.py`)

**Required Config Keys**:
- `credentials_json`: service account key JSON (required)
- `folder_id`: restrict to a folder subtree — the id from the folder URL `drive.google.com/drive/folders/<ID>` (optional)
- `shared_drive_id`: restrict to a Shared Drive (optional)

**Authentication**: Google service account (read-only, `drive.readonly`). Unlike GitHub/Notion, Google has no simple "personal token" — you use a **service account** (a robot identity with its own email), then **share your folder with that robot**. It only sees what you explicitly share with it.

**Setup — form fields & how to get the JSON:**

Form fields (KB Admin → Sources → Add → Google Drive):

- **Service Account JSON** *(secret)* — paste the **entire contents** of the downloaded key file (see below).
- **Folder ID** *(optional)* — index just one folder (and its subfolders). It's the id in the folder's URL: `drive.google.com/drive/folders/`**`1AbC…`**. Leave empty to index **everything shared with the service account**.
- **Shared Drive ID** *(optional)* — a **Shared Drive** is a team-owned space in Google Workspace (paid), separate from anyone's personal "My Drive". **Personal/free Google accounts don't have Shared Drives — leave this empty.** Set it only to index a whole team drive the service account was added to.

Get the JSON key:

1. Open **console.cloud.google.com** → create a project (top-left project picker → New Project).
2. Search **Google Drive API** → **Enable**.
3. Search **Service accounts** → **Create service account** → name it → **Done**.
4. Open the new service account → **Keys** tab → **Add key → Create new key → JSON** → a `.json` file downloads. This is your key.
5. Inside that file, find `"client_email": "…@….iam.gserviceaccount.com"` — copy that address.
6. In Google Drive, right-click the folder to index → **Share** → paste that `client_email` → role **Viewer** → Send. (A "no Google account / email won't be delivered" warning is normal — the robot still gets access.)
7. Paste the full JSON file contents into **Service Account JSON**; optionally add the **Folder ID** from step 6's folder URL.

> **Note:** a service account cannot see a person's private "My Drive" automatically — only folders/files (or a Shared Drive) explicitly shared with its `client_email`.

**What Gets Indexed**:
- Google Docs (exported as Markdown), Sheets (exported as CSV — first tab only), Slides (exported as plain text)
- Binary files by extension: `.pdf`, `.docx`, `.xlsx`, `.csv`, `.html`, `.htm`, `.txt`, `.md` (downloaded and text-extracted)
- Binary files larger than 1 MB and unsupported MIME types are skipped
- Metadata: `type=gdrive`, `file_id`, `mime_type`, `owner`

**Incremental Sync**: Uses the Google Drive **Changes API**, not `modifiedTime`. The first sync (and any `force_full`) runs a full sweep of the configured scope and captures a `startPageToken`, persisted per connection in the `connector_state` table. Later syncs page `changes.list` from that token, which reports files **added, moved, or edited** in the account's view. Deleted/trashed changes are skipped (deletions are not removed from the index). An expired token (HTTP 410) falls back to a full sweep.

> **No-scope / `sharedWithMe` mode — verified behavior:** with neither `folder_id` nor `shared_drive_id` set, `changes.list` runs against the service account's own corpus (no `driveId`). Live testing confirms this feed **does** surface changes to shared content in this mode: a file newly added to a shared folder appears as `new`, and an in-place edit of an already-indexed shared file appears as `updated` (same `file_id`, no duplicate) — both picked up by a normal incremental sync, no `force_full` needed. Google does not *formally* guarantee change-feed coverage for purely-shared files across all account types, so for mission-critical shared-content freshness a periodic `force_full` remains a safe belt-and-suspenders; in practice the incremental path works.

**Notes**: With neither `folder_id` nor `shared_drive_id` set, the connector indexes everything shared with the service account. A service account cannot see a user's personal "My Drive" automatically — only folders/files (or a Shared Drive) explicitly shared with it.

### MCP Client (Universal Connector)

**Implementation**: `src/metronix/mcp/` — `client.py`, `adapter.py`, `sync.py`, `registry.py`, `config.py`

The MCP Client connects to any external tool that speaks the [Model Context Protocol](https://modelcontextprotocol.io/). Instead of writing a native connector for each source, you register an MCP server and Metronix automatically:
- Discovers its tools via `tools/list`
- Classifies tools as "read" (for sync) or "action" (for execution)
- Calls read tools during `/mcp sync` to ingest documents
- Calls action tools when the user requests an action ("create a Jira ticket...")

**Bot Commands**:
```
/mcp list                          — List registered MCP servers
/mcp add <name> <command> [args]   — Register an MCP server
/mcp remove <name>                 — Remove an MCP server
/mcp sync <name> [full]            — Sync documents from one server
/mcp sync-all [full]               — Sync all registered servers
/mcp tools <name>                  — List tools exposed by a server
```

**Example — adding a GitHub MCP server**:
```
/mcp add github npx @modelcontextprotocol/server-github
/mcp sync github
```

After sync, documents from the server are indexed into Qdrant and available via search.

**How it works**:
1. `MCPClient` (`client.py`) connects via SSE transport, lists tools, calls tools
2. `GenericMCPAdapter` (`adapter.py`) classifies tools: read tools (names containing `list`, `get`, `search`, `read`, `fetch`) vs action tools (everything else)
3. `mcp_sync_server()` (`sync.py`) calls each read tool, converts results to Documents, indexes via the standard pipeline
4. `ActionPlanner` (`action_planner.py`) uses LLM to pick the right action tool + arguments from user intent
5. `ActionExecutor` (`action_executor.py`) calls the selected tool via MCP and returns the result

**Incremental Sync**: Passes `since` timestamp as argument to read tools that accept it

### Planned Native Connectors

The following native connectors are planned but not yet implemented. In the meantime, you can connect these sources via MCP servers:

- **Slack History** — channel messages, threads

## Writing a New Connector

For quick integrations, consider using an MCP server instead (see MCP Client section above). For major integrations that need deep control over fetching, pagination, and metadata, write a native connector:

### Step 1: Implement ConnectorInterface

Create a new file in `src/metronix/connectors/`:

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

### Usage in Benchmarker (DocumentSampler)

The benchmarker module uses connectors through `DocumentSampler` — an adapter that bridges Metronix's `ConnectorInterface` with BenchmarkQED's expected document format.

**How it works:**

1. `DocumentSampler` receives a `Connection` object and connector config
2. Creates a connector via `ConnectorRegistry.create(connector_type)`
3. Calls `connector.configure()` then `connector.fetch()` to get all documents
4. Randomly samples N documents from the result
5. Maps `metronix.core.models.Document` → `QEDDocument` (benchmarker format)

**Field mapping:**

| Document (Metronix) | QEDDocument (Benchmarker) |
|---------------------|--------------------------|
| `source_id` | `source_id` |
| `title` | `title` |
| `content` | `text` |
| `source_type` | `source_type` |
| `url` | `url` |

**Sample size invariant:** result always contains `min(N, len(documents))` items. If the connector returns fewer documents than requested, all are returned.

**Location:** `src/metronix/benchmarker/services/document_sampler.py`
