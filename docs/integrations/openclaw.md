# OpenClaw Integration

OpenClaw should connect to Metronix through MCP when MCP client support is available.

Use:

```text
URL: http://localhost:8000/mcp
# = metronix-full-api container (metronix-core:8000/mcp from Docker network)
Authorization: Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id: <stable-agent-id>   # same id as agent_id in memory tools; match Metronix Console agent UUID
```

Verify with `metronix_status` and memory list/search tools. See `mcp-reference.md`
for tool details.
