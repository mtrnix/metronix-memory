# Hermes Agent

## Recommended mode

Use Metronix Memory as an HTTP MCP server.

This is the important distinction: Metronix Memory is not a Hermes-native memory provider plugin.
It is an external MCP backend Hermes can call for search, memory, and retrieval.

## What you need

- Metronix Memory running locally or remotely
- `METATRON_MCP_API_KEY` from the Metronix Memory `.env`
- a stable Hermes agent id
- a workspace id such as `MTRNIX`

## Connection values

```text
URL:          http://localhost:8001/mcp
Authorization: Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:    <stable-hermes-agent-id>
```

## Example Hermes config

```yaml
mcp_servers:
  metatron:
    url: http://localhost:8001/mcp
    headers:
      Authorization: "Bearer <METATRON_MCP_API_KEY>"
      X-Agent-Id: "<AGENT_UUID>"
    timeout: 180
    connect_timeout: 60
```

Restart Hermes after changing MCP configuration.

## Verify

Call:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<AGENT_UUID>", limit=5)
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8001/health`), and check that `METATRON_MCP_API_KEY` in your `.env` matches the key in the Hermes config.

**Tools not appearing after registration:** Restart Hermes after changing MCP configuration — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly in the Hermes YAML config. The key must match `METATRON_MCP_API_KEY` in `.env`.

## Recommendation

If you already use Hermes-native memory providers, keep them separate mentally.
Metronix Memory is the durable shared memory and knowledge backend. Treat it like the source of
truth you can inspect, not an invisible sidecar.
