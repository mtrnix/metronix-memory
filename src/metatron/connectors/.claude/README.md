# Connectors

## Overview
L3 — data-source connectors. Each connector fetches `Document` objects from an external
system and passes them to the ingestion pipeline. All implement `ConnectorInterface` (L0).
Currently all synchronous (TODO: async migration on most).

## Files

### `registry.py`
`ConnectorRegistry` — maps `connector_type` strings to `ConnectorInterface` classes.

`register(connector_type, cls)` — register a connector class.
`get(connector_type) -> ConnectorInterface` — instantiate connector by type string.
`list_types() -> list[str]` — all registered types.

`register_builtins(registry)` — registers all built-in connectors:
`confluence`, `jira`, `notion`, `github`, `gdrive`, `slack_history`, `files`.

Used by `api/routes/connections.py` (module-level singleton `_registry`).

### `confluence.py`
`ConfluenceConnector` — fetches Confluence wiki pages.
Uses `atlassian-python-api`. CQL query: `space = {space_key} AND lastModified > {since}`.
Config: `url`, `username`, `api_token`, `space_key`.
`fetch()` → calls `process_confluence_page()` → `Document` per page.
Incremental sync via `since` parameter passed to CQL.

### `confluence_processing.py`
`process_confluence_page(page_data) -> Document`
— Converts atlassian API page dict to `Document`.
Calls `process_html()` processor for body content.
Extracts title, author, dates, URL, labels as tags.

### `jira.py`
`JiraConnector` — fetches Jira issues (summary, description, comments, changelog).
Uses `atlassian-python-api` v4+ with `enhanced_jql`.
Config: `url`, `username`, `api_token`, `project_key`.
`fetch()` → JQL: `project = {key} ORDER BY updated DESC`, with `since` filter.
Calls `process_jira_issue()` and `jira_issue_to_markdown()`.

### `jira_processing.py`
`process_jira_issue(issue_data) -> Document`
— Converts Jira issue dict to `Document`.
`jira_issue_to_markdown(issue_data) -> str`
— Formats issue fields + comments as readable Markdown for indexing.

### `notion.py`
`NotionConnector` — async. Uses official `notion-client` `AsyncClient`.
Config: `api_token`.
`fetch()` — searches all pages/databases via `client.search()`,
fetches block tree via `fetch_all_blocks()`.
Incremental sync via `last_edited_time` filter.
Rate limit delay: `_RATE_LIMIT_DELAY = 4` seconds between page fetches.

### `notion_processing.py`
`fetch_all_blocks(client, page_id) -> list` — recursive block tree fetch.
`blocks_to_markdown(blocks) -> str` — Notion block types → Markdown.
`get_page_title(page) -> str` — extracts title from page properties.

### `github.py`
`GitHubConnector` — fetches README, issues, PRs, wiki pages.
Uses `PyGithub`. Config: `token`, `org`, `repos` (comma-separated or `"*"` for all).
Creates separate `Document` per: README, each open/closed issue, each PR discussion.

### `gdrive.py`
`GDriveConnector` — Google Drive via service account or OAuth.
Config: `credentials_json` (path to service account JSON), `folder_id` (optional), `shared_drive_id` (optional).
Exports Google Docs as plain text, Sheets as CSV, other files by MIME type.
Uses `google-api-python-client`.

### `slack_history.py`
`SlackHistoryConnector` — Slack channel message history.
Config: `bot_token` (xoxb-), `channels` (comma-separated names/IDs or `"*"`).
Uses Slack Web API (`conversations.history`, `conversations.list`).
Groups thread replies under parent message. One `Document` per channel per day.

### `files.py`
`FilesConnector` — indexes already-uploaded local files.
Config: `file_store_path` (from Settings).
Reads from `FileStore`, passes through appropriate `ProcessorInterface` per file type.
Used when user uploads via `POST /api/v1/upload` or `POST /api/v1/files/`.

### `sync_state.py`
`SyncState` — persists last sync timestamp per `(connection_id, connector_type)`.
Stored in PostgreSQL `config` table as JSON.
`get_last_sync(connection_id) -> datetime | None`
`set_last_sync(connection_id, timestamp)`
Used by all connectors for incremental sync (`since` parameter).

## Key Patterns
- **`ConnectorInterface` lifecycle** — `configure(connection, decrypted_config)` → `fetch(workspace_id, since)` → documents to ingestion pipeline
- **Incremental sync** — all connectors accept `since: datetime | None`; `None` = full sync
- **Config encryption** — `Connection.config_encrypted` is decrypted by connections API before passing to `configure()`
- **Registry pattern** — `register_builtins()` is called once at app startup; enterprise connectors add via `registry.register()`
- **Sync vs async** — Confluence, Jira, GitHub, GDrive, Slack are sync (TODO: async); Notion is async (uses `asyncio.run()` wrapper in fetch)

## Dependencies
- **Depends on**: `core.interfaces` (ConnectorInterface), `core.models` (Connection, Document), `ingestion.processors` (html, tabular, pdf etc.), `storage.file_store` (FilesConnector), `storage.postgres` (sync_state)
- **Depended on by**: `api.routes.connections` (CRUD + sync trigger), `ingestion.pipeline` (receives documents)
