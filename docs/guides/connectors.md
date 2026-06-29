# Connectors Guide

Connectors fetch documents from external systems and pass them into Metronix Memory's ingestion
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

For detailed connector fields, see `docs/CONNECTORS.md` and `docs/API.md`.
