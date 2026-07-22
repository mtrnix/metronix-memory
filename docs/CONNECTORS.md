# Connectors

Connectors ingest documents from external systems into a Metronix workspace. Create and
manage them through the Connections API or the Admin Console; credentials are encrypted at
rest and must never be committed to configuration files.

## Supported connector types

The built-in connector registry currently provides:

- Confluence
- Jira
- Notion
- GitHub
- Google Drive (`gdrive`)
- Slack history (`slack_history`)
- files

The server is the source of truth for which types and fields are available. Query the schema
endpoint before creating a connection:

```bash
curl http://localhost:8000/api/v1/connections/schemas/
```

See the [Connections API reference](API.md#connections) for every endpoint and request
shape.

## Create and sync a connector

Create a connection for a workspace, then test its credentials before starting a sync:

```bash
curl -X POST "http://localhost:8000/api/v1/connections/?workspace_id=MTRNIX" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "connector_type": "confluence",
    "name": "Engineering wiki",
    "config": {
      "url": "https://example.atlassian.net/wiki",
      "username": "bot@example.com",
      "api_token": "<secret>"
    }
  }'

curl -X POST "http://localhost:8000/api/v1/connections/<connection-id>/test/?workspace_id=MTRNIX" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/api/v1/connections/<connection-id>/sync/?workspace_id=MTRNIX" \
  -H "Authorization: Bearer $TOKEN"
```

Set `sync_cron` when creating or updating a connection to schedule incremental syncs. Add
`force_full=true` to a sync request to bypass its incremental cursor for that run.

## Runtime behavior

Each connector implements `ConnectorInterface` in
[`src/metronix/core/interfaces.py`](../src/metronix/core/interfaces.py). Metronix configures
it from a stored `Connection`, checks connectivity, and fetches documents for the selected
workspace. A scheduled sync reuses `last_synced_at` as its incremental cursor; a first or
forced full sync fetches without that cursor.

Connector implementations and registration live in
[`src/metronix/connectors/`](../src/metronix/connectors/). To add a connector, implement the
interface, register it in `register_builtins`, and add its public schema in
`src/metronix/connectors/schemas.py` so the API can validate its configuration.
