# MCP Reference

The canonical MCP tool reference is [`../MCP_API.md`](../MCP_API.md).

All HTTP MCP clients should connect to:

```text
http://localhost:8000/mcp
```

Required headers:

```text
Authorization: Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id: <stable-agent-id>
```
