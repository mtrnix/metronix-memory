# OpenClaw Integration

OpenClaw should connect to Metronix through MCP when MCP client support is available.

Use:

```text
URL: http://localhost:8000/mcp
Authorization: Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id: <stable-agent-id>
```

Verify with `metronix_status` and memory list/search tools. See `mcp-reference.md`
for tool details.
