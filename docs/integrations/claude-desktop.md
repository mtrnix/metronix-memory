<!-- TODO: This guide needs a full rewrite. Currently missing: prerequisites section, numbered setup steps, expanded verify section. -->

# Claude Desktop Integration

Configure Claude Desktop as an MCP client for Metronix.

Required values:

- MCP URL: `http://localhost:8000/mcp` — default on the host; **`metronix-full-api`** container (`metronix-core` in Compose), port **8000**, path **`/mcp`**. From Docker network: `http://metronix-core:8000/mcp`.
- Header: `Authorization: Bearer <METRONIX_MCP_API_KEY>`
- Header: `X-Agent-Id: <stable-agent-id>` — agent identity for MCP/memory; must match the
  agent UUID in Metronix Console (corporate version) when linking there

After adding the MCP server, restart Claude Desktop and verify the `metronix_*` tools
are visible. Use `metronix_status` first, then `metronix_memory_list` with both
`workspace_id` and `agent_id`.

Use `../../connecting_to_agent.md` when you want an agent to perform the setup steps.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in Claude Desktop.

**Tools not appearing after registration:** Restart Claude Desktop after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.
