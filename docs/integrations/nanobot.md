# NanoBot

## Recommended mode

Use Metronix Memory through MCP if NanoBot supports external MCP servers. Otherwise use the
OpenAI-compatible endpoint for chat-style access.

## MCP values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-nanobot-agent-id>
```

## OpenAI-compatible values

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

## Verify

After setup, confirm the connection works:

- MCP path: call `metatron_status(workspace_id="MTRNIX")` and confirm a status response.
- OpenAI-compatible path: send a test chat request against `metatron-rag-<workspace_id>` and confirm a response.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8001/health`), and check that `METATRON_MCP_API_KEY` in your `.env` matches the key configured in NanoBot.

**Tools not appearing after registration:** Restart NanoBot after adding the MCP server — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METATRON_MCP_API_KEY` in `.env`.

## Recommendation

If NanoBot is supposed to remember things durably, pick MCP. If it's just a chat shell,
`/v1` is enough to get moving.
