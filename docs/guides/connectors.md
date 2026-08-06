# Connectors Guide

Connectors fetch documents from external systems and pass them into Metronix's ingestion
pipeline.

## Common Connectors

- Confluence
- Jira
- Notion
- GitHub
- Google Drive
- Slack history
- Local files

## Sync Flow

Connector sync runs:

```text
fetch -> parse -> chunk -> embed -> store metadata -> update vector and graph indexes
```

Credentials should be stored through the Connections API or UI, not committed to files.

For connector types, sync behavior, and extension points, see
[`CONNECTORS.md`](../CONNECTORS.md). For request fields, see the
[Connections API reference](../API.md#connections).
