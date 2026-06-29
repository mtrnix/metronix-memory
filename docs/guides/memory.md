# Memory Guide

Metronix Memory stores durable agent context separately from chat history.

## Kinds

- `fact` — durable factual statements.
- `preference` — stable user or team preferences.
- `pinned` — explicit must-remember instructions.

## Access Paths

- MCP tools: `metatron_memory_store`, `metatron_memory_search`,
  `metatron_memory_list`, `metatron_memory_update`, and related review tools.
- REST API: `/api/v1/memory/*`.

Always pass both `workspace_id` and `agent_id` for agent-scoped memory operations.

## Freshness

The freshness worker detects stale, duplicate, and conflicting records and can queue
records for review. Run it when you need lifecycle management beyond simple storage.
