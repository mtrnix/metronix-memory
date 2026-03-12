# Connectors

## Overview
L3 — data-source connectors. Each connector fetches `Document` objects from an external
system and passes them to the ingestion pipeline. All implement `ConnectorInterface` (L0).
Currently all synchronous (TODO: async migration on most).

## Implementation Status

| Connector | Status | Notes |
|-----------|--------|-------|
| `confluence` | ✅ Working | Full CQL-based sync + incremental via `lastModified` |
| `jira` | ✅ Working | Full JQL sync + incremental, ADF extraction, changelog |
| `notion` | ✅ Working | Async, recursive block fetch, incremental via `last_edited_time` |
| `github` | 🚧 Scaffold | `configure()` is a no-op (TODO), `fetch()` raises `NotImplementedError` |
| `gdrive` | 🚧 Scaffold | `configure()` is a no-op (TODO), `fetch()` raises `NotImplementedError` |
| `slack_history` | 🚧 Scaffold | `fetch()` raises `NotImplementedError` |
| `files` | 🚧 Scaffold | `fetch()` raises `NotImplementedError` — upload flow uses ingestion pipeline directly |

**3 of 7 connectors are fully working.** GitHub, GDrive, Slack history, and Files are registered
in the registry and accepted via the API, but will fail at sync time.

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
🚧 `GitHubConnector` — scaffold only.
`configure()` is a no-op (TODO comment). `fetch()` raises `NotImplementedError`.
Intended design: fetch README, issues, PRs, wiki pages via `PyGithub`.
Config keys: `token`, `org`, `repos` (comma-separated or `"*"` for all).

### `gdrive.py`
🚧 `GDriveConnector` — scaffold only.
`configure()` is a no-op (TODO comment). `fetch()` raises `NotImplementedError`.
Intended design: export Google Docs as plain text, Sheets as CSV via `google-api-python-client`.
Config keys: `credentials_json`, `folder_id` (optional), `shared_drive_id` (optional).

### `slack_history.py`
🚧 `SlackHistoryConnector` — scaffold only.
`fetch()` raises `NotImplementedError`.
Intended design: index channel message history via Slack Web API (`conversations.history`).
Config keys: `bot_token` (xoxb-), `channels` (comma-separated names/IDs or `"*"`).

### `files.py`
🚧 `FilesConnector` — scaffold only.
`fetch()` raises `NotImplementedError`.
Note: the upload flow (`POST /api/v1/upload`, `POST /api/v1/files/`) bypasses this connector
entirely — it passes bytes directly to the ingestion pipeline.
Config keys: `file_store_path` (from Settings).

### `sync_state.py`
`SyncState` — **file-based** persistence for last sync timestamps.
Stored in `.metatron/sync_state.json` (not PostgreSQL).
Key format: `"{workspace_id}:{source_type}"` → ISO timestamp string.

`get_last_sync(workspace_id, source_type) -> datetime | None`
`set_last_sync(workspace_id, source_type, ts=None)` — defaults to `datetime.now(UTC)`
`clear(workspace_id, source_type)` — forces full sync on next run

State file is created automatically (`mkdir parents=True`). Load errors return empty dict (warn + continue).

## Key Patterns
- **`ConnectorInterface` lifecycle** — `configure(connection, decrypted_config)` → `fetch(workspace_id, since)` → documents to ingestion pipeline
- **Incremental sync** — all connectors accept `since: datetime | None`; `None` = full sync
- **Config encryption** — `Connection.config_encrypted` is decrypted by connections API before passing to `configure()`
- **Registry pattern** — `register_builtins()` is called once at app startup; enterprise connectors add via `registry.register()`
- **Sync vs async** — Confluence and Jira are sync (TODO: async migration); Notion is natively async (`AsyncClient`)
- **Scaffold connectors fail silently at registration** — GitHub, GDrive, Slack history, Files are registered in the registry and accepted by the connections API, but raise `NotImplementedError` when sync is triggered

## Dependencies
- **Depends on**: `core.interfaces` (ConnectorInterface), `core.models` (Connection, Document), `ingestion.processors` (html, tabular, pdf etc.), `storage.file_store` (FilesConnector). `SyncState` has no DB dependency — uses `.metatron/sync_state.json`
- **Depended on by**: `api.routes.connections` (CRUD + sync trigger), `ingestion.pipeline` (receives documents)
