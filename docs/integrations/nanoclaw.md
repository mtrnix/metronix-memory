# NanoClaw

## Recommended mode

Use Metronix Memory through MCP.

## Connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-nanoclaw-agent-id>
```

## Important distinction

NanoClaw may already have its own provider and memory model. Metronix Memory does not automatically
replace or migrate that state.

Supported path today:

- keep NanoClaw's native runtime behavior
- connect NanoClaw to Metronix Memory as an external MCP server
- use Metronix Memory for durable memory and knowledge retrieval

## Verify

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<stable-nanoclaw-agent-id>", limit=5)
```

Then store a tiny test fact and confirm it is searchable.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8001/health`), and check that `METATRON_MCP_API_KEY` in your `.env` matches the key configured in NanoClaw.

**Tools not appearing after registration:** Restart NanoClaw after adding the MCP server — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METATRON_MCP_API_KEY` in `.env`.
