# Claude Desktop Integration

Configure Claude Desktop as an MCP client for Metronix Memory.

Required values:

- MCP URL: `http://localhost:8001/mcp`
- Header: `Authorization: Bearer <METATRON_MCP_API_KEY>`
- Header: `X-Agent-Id: <stable-agent-id>`

After adding the MCP server, restart Claude Desktop and verify the `metatron_*` tools
are visible. Use `metatron_status` first, then `metatron_memory_list` with both
`workspace_id` and `agent_id`.

Use `../../connecting_to_agent.md` when you want an agent to perform the setup steps.
