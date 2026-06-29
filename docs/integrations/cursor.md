# Cursor Integration

Use Metronix Memory through Cursor's MCP support.

1. Start Metronix Memory and confirm `curl http://localhost:8001/health`.
2. Set `METATRON_MCP_API_KEY` in `.env`.
3. Add an MCP server entry for `http://localhost:8001/mcp`.
4. Send headers:
   - `Authorization: Bearer <METATRON_MCP_API_KEY>`
   - `X-Agent-Id: <stable-agent-id>`
5. Restart Cursor if MCP servers are loaded only at startup.
6. Verify with `metatron_status` and `metatron_memory_list`.

The prompt in `../../connecting_to_agent.md` can be pasted into an agent to perform the
setup interactively.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8001/health`), and check that `METATRON_MCP_API_KEY` in your `.env` matches the key configured in Cursor.

**Tools not appearing after registration:** Restart Cursor after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METATRON_MCP_API_KEY` in `.env`.
