# Legacy And Compatibility Surfaces

This page documents older surfaces that remain in Metronix Memory for compatibility.
New integrations should prefer MCP, the OpenAI-compatible API, or the REST APIs.

## Legacy Channels

`src/metatron/channels/` contains Telegram, Discord, and Slack bot integrations.
They still work when the optional channel dependencies are installed, but new chat
experiences should be built outside Core and connect through MCP or the
OpenAI-compatible API.

Recommended replacement: Open WebUI, Hermes, Cursor, Claude Desktop, LibreChat, or any
MCP-capable agent runtime.

## Built-In Chat Route

`/api/v1/chat` is retained for compatibility with older deployments. New user-facing
chat clients should use `/v1/chat/completions` or MCP tools instead.

Recommended replacement: OpenAI-compatible `/v1/chat/completions`.

## Skills Stubs

The `skills/` package and related API routes are dormant. The preferred capability
description mechanism is MCP tool metadata.

Recommended replacement: MCP server tools and integration-specific documentation.

## Benchmarker

The benchmarker package is a development and evaluation utility. It is optional and loaded
defensively so missing benchmark dependencies do not prevent the API from starting.

Recommended replacement for production use: runtime observability and RAG traces.

## Memgraph Environment Aliases

Some `MEMGRAPH_*` environment variable aliases are still accepted for older deployments
that predate the Neo4j migration.

Recommended replacement: use `NEO4J_*` variables.

## Compatibility Shims

Some modules re-export moved memory/freshness functionality to avoid breaking external
callers immediately. These shims should not be used by new code.

Recommended replacement: import from the canonical module documented next to the shim.
