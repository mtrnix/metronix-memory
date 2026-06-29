# Cursor Integration

Use Metronix through Cursor's MCP support.

1. Start Metronix and confirm `curl http://localhost:8000/health`.
2. Set `METRONIX_MCP_API_KEY` in `.env`.
3. Add an MCP server entry for `http://localhost:8000/mcp` (the **`metronix-full-api`** container, path `/mcp`; from Docker network: `http://metronix-core:8000/mcp`).
4. Send headers:
   - `Authorization: Bearer <METRONIX_MCP_API_KEY>`
   - `X-Agent-Id: <stable-agent-id>` — identifies the agent for MCP and memory; must match
     the agent UUID in Metronix Console (corporate version) when linking a runtime there
5. Restart Cursor if MCP servers are loaded only at startup.
6. Verify with `metronix_status` and `metronix_memory_list`.

The prompt in `../../connecting_to_agent.md` can be pasted into an agent to perform the
setup interactively.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in Cursor.

**Tools not appearing after registration:** Restart Cursor after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.
