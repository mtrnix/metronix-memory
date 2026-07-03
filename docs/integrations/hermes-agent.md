# Hermes Agent

## Recommended mode

Use Metronix Memory as an HTTP MCP server today.

That is still the recommended production path right now.
It is the best-supported integration for search, memory, and retrieval.

If you want native Hermes memory-provider hooks such as prefetch injection
and write-through from `memory(action="add")`, build that as a standalone
Hermes plugin repo rather than an in-tree Hermes contribution. A scaffold for
that direction lives in:

- `standalone/hermes-memory-metronix/`

## What you need

- Metronix Memory running locally or remotely
- `METRONIX_MCP_API_KEY` from the Metronix Memory `.env`
- a stable Hermes agent id
- a workspace id such as `MTRNIX`

## Connection values

```text
URL:          http://localhost:8000/mcp
Authorization: Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:    <stable-hermes-agent-id>
```

## Example Hermes config

```yaml
mcp_servers:
  metronix:
    url: http://localhost:8000/mcp
    headers:
      Authorization: "Bearer <METRONIX_MCP_API_KEY>"
      X-Agent-Id: "<AGENT_UUID>"
    timeout: 180
    connect_timeout: 60
```

Restart Hermes after changing MCP configuration.

## Verify

Call:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_list(workspace_id="MTRNIX", agent_id="<AGENT_UUID>", limit=5)
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key in the Hermes config.

**Tools not appearing after registration:** Restart Hermes after changing MCP configuration — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly in the Hermes YAML config. The key must match `METRONIX_MCP_API_KEY` in `.env`.

## Recommendation

If you already use Hermes-native memory providers, keep them separate mentally.
Metronix Memory is the durable shared memory and knowledge backend. Treat it like the source of
truth you can inspect, not an invisible sidecar.
