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

### `schemas.py`
`ConnectorSchema` + `ConfigField` — dataclass-based schema definitions for all connector types.
Defines required/optional fields, field types (`string`, `url`, `secret`, `number`, `boolean`),
and categories (`connector` vs `channel`).

`CONNECTOR_SCHEMAS` — dict mapping connector_type string to `ConnectorSchema`.
Covers: confluence, jira, notion, github, gdrive, slack_history, telegram, discord, slack.

Key functions:
- `get_schema(connector_type) -> ConnectorSchema | None`
- `validate_config(connector_type, config) -> list[str]` — returns error messages (empty = valid)
- `mask_secrets(connector_type, config) -> dict` — replaces secret fields with `"***"`
- `merge_config(connector_type, old_config, new_config) -> dict` — preserves old secret values when new value is `"***"`

Used by `storage/postgres.py` connection CRUD (create, list, update) and will be used by
API routes for form generation and request validation.

## DB-Based Connection Config
Connections are stored in the `connections` table (PostgreSQL) with encrypted config:

**Table columns**: id, workspace_id, connector_type, name, config_encrypted (Fernet),
status, enabled, error_message, last_synced_at, created_at, updated_at,
`sync_cron TEXT DEFAULT '0 3 * * *'` (cron schedule for autosync; NULL for channel rows),
`next_run_at TIMESTAMPTZ NULL` (next scheduled run; NULL = trigger on the very next scheduler tick).

**Autosync scheduling (MTRNIX-396):** connector rows are scheduled via a cron expression
(`sync_cron`, default nightly `0 3 * * *`). Channel rows (telegram/discord/slack) have
`sync_cron=NULL` and are excluded from autosync entirely. The in-process `AutosyncScheduler`
(see `api/autosync.py`) reads due connections each tick, atomically claims them via
`claim_connection_for_autosync`, and runs the same `_run_connection_sync` helper used by
the manual `POST /connections/{id}/sync` path. Coalesce-to-one for missed runs.

**CRUD in `storage/postgres.py`**:
- `create_connection(workspace_id, connector_type, name, config, fernet_key)` — validates, encrypts, inserts
- `list_connections(workspace_id, fernet_key)` — returns all with masked secrets
- `get_connection(connection_id, fernet_key)` — single connection, masked secrets
- `get_connection_decrypted(connection_id, fernet_key)` — plaintext config (internal use only)
- `update_connection(connection_id, updates, fernet_key)` — handles secret merging via `merge_config()`
- `delete_connection(connection_id)` — hard delete
- `update_connection_status(connection_id, status, error_message, last_synced_at)` — status tracking

**Security**: secrets are never logged or returned in plaintext via list/get endpoints.
`mask_secrets()` replaces secret fields with `"***"`. `merge_config()` preserves old secrets
when update payload contains `"***"`.

## Configuration Model
**All connector credentials are stored in the database** (encrypted with Fernet), not in env vars.
The `config.py` Settings class no longer contains connector-specific env vars (confluence_url, jira_url, etc.).

- Connectors receive config via `configure(connection, decrypted_config)` — the decrypted_config dict
  comes from `PostgresStore.get_connection_decrypted()`.
- The `/sync` chat command is deprecated — sync is triggered via `POST /api/v1/connections/{id}/sync`.
- Channel tokens (telegram, discord, slack) remain in env vars since they are used at bot startup.

## Key Patterns
- **`ConnectorInterface` lifecycle** — `configure(connection, decrypted_config)` → `fetch(workspace_id, since)` → documents to ingestion pipeline
- **Incremental sync** — all connectors accept `since: datetime | None`; `None` = full sync
- **Config encryption** — `Connection.config_encrypted` is decrypted by connections API before passing to `configure()`
- **Registry pattern** — `register_builtins()` is called once at app startup; enterprise connectors add via `registry.register()`
- **Sync vs async** — Confluence and Jira are sync (TODO: async migration); Notion is natively async (`AsyncClient`)
- **Scaffold connectors fail silently at registration** — GitHub, GDrive, Slack history, Files are registered in the registry and accepted by the connections API, but raise `NotImplementedError` when sync is triggered

## Dependencies
- **Depends on**: `core.interfaces` (ConnectorInterface), `core.models` (Connection, Document), `ingestion.processors` (html, tabular, pdf etc.), `storage.file_store` (FilesConnector), `storage.encryption` (Fernet encrypt/decrypt). `SyncState` has no DB dependency — uses `.metatron/sync_state.json`
- **Depended on by**: `api.routes.connections` (CRUD + sync trigger), `ingestion.pipeline` (receives documents), `storage.postgres` (imports schemas for validation/masking)
