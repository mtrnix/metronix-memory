# Ingestion Guide

Metronix Memory can ingest data through connectors, file upload APIs, and MCP tools.

## File Upload

Use the REST file endpoints documented in `docs/API.md` when you have local files to
send to Metronix Memory. The server receives file bytes and runs them through the normal
processing pipeline.

Do not expose arbitrary server-local path ingestion in public deployments. If an agent
needs to ingest a folder, let the agent enumerate files locally and upload supported
files through REST or MCP.

## Connectors

Connector records hold source configuration and credentials. Sync jobs fetch remote
documents, parse them, chunk them, embed them, and write derived data to Qdrant and Neo4j.

Common connector families include Confluence, Jira, Notion, GitHub, Google Drive, Slack
history, and local files.

## MCP Store

MCP clients can use `metatron_store` for direct document ingestion and source sync tools
for configured MCP sources. See `docs/MCP_API.md` for schemas.
