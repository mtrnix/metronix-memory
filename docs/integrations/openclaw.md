# OpenClaw

## Recommended mode

Use Metronix Memory through MCP.

## What you need

- Metronix Memory running
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

Add Metronix Memory as an external MCP server in OpenClaw using the values above. If OpenClaw
loads MCP servers only at startup, restart it after saving the config.

## Verify

Use these first:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<stable-openclaw-agent-id>", limit=5)
```

Then store a small test fact and search for it.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8001/health`), and check that `METATRON_MCP_API_KEY` in your `.env` matches the key configured in OpenClaw.

**Tools not appearing after registration:** Restart OpenClaw after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METATRON_MCP_API_KEY` in `.env`.

## Notes

Metronix Memory gives OpenClaw a better memory and knowledge surface. It does not replace
every internal runtime abstraction OpenClaw may already have.
