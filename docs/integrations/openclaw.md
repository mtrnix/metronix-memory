# OpenClaw

## Recommended mode

Use Metatron through MCP.

## What you need

- Metatron running
- `METATRON_MCP_API_KEY`
- a stable `X-Agent-Id`
- a workspace id

## Connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-openclaw-agent-id>
```

## Setup

Add Metatron as an external MCP server in OpenClaw using the values above. If OpenClaw
loads MCP servers only at startup, restart it after saving the config.

## Verify

Use these first:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<stable-openclaw-agent-id>", limit=5)
```

Then store a small test fact and search for it.

## Notes

Metatron gives OpenClaw a better memory and knowledge surface. It does not magically
replace every internal runtime abstraction OpenClaw may already have. Software rarely
works by telepathy, despite the optimism of many integration docs.
