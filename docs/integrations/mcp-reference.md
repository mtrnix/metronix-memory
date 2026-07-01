# MCP Reference

The canonical MCP tool reference is [`../MCP_API.md`](../MCP_API.md).

All HTTP MCP clients should connect to:

```text
http://localhost:8000/mcp
```

From the host this is the default. It is the **`metronix-full-api`** container (`metronix-core` service in `docker-compose.yml`) on port **8000** with path **`/mcp`**. From another container on the same Docker network use `http://metronix-core:8000/mcp` instead of `localhost`.

See [`../MCP_API.md`](../MCP_API.md#finding-the-mcp-url) for details.

Required headers:

```text
Authorization: Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id: <stable-agent-id>
```

`X-Agent-Id` scopes MCP and memory to one agent; use the same value as `agent_id` in memory
tools and as the agent UUID in Metronix Console (corporate version) when linking a runtime.
See [`../guides/agents-and-workspaces.md`](../guides/agents-and-workspaces.md).
