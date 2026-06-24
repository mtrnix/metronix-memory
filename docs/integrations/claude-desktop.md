# Claude Desktop Integration

Configure Claude Desktop as an MCP client for Metronix.

Required values:

- MCP URL: `http://localhost:8000/mcp`
- Header: `Authorization: Bearer <METRONIX_MCP_API_KEY>`
- Header: `X-Agent-Id: <stable-agent-id>`

After adding the MCP server, restart Claude Desktop and verify the `metronix_*` tools
are visible. Use `metronix_status` first, then `metronix_memory_list` with both
`workspace_id` and `agent_id`.

Use `../../connecting_to_agent.md` when you want an agent to perform the setup steps.
