# NanoBot

> **MCP authentication mode:** The example targets local `AUTH_ENABLED=false` and uses
> `METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, put a user JWT in the same Bearer
> header; the shared key is ignored.

## Recommended mode

Use Metronix Memory through MCP if NanoBot supports external MCP servers. Otherwise use the
OpenAI-compatible endpoint for chat-style access.

## MCP values

```text
URL:            http://localhost:8000/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-nanobot-agent-id>
```

## OpenAI-compatible values

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

## Verify

After setup, confirm the connection works:

- MCP path: call `metronix_status(workspace_id="MTRNIX")` and confirm a status response.
- OpenAI-compatible path: send a test chat request against `metronix-rag-<workspace_id>` and confirm a response.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in NanoBot.

**Tools not appearing after registration:** Restart NanoBot after adding the MCP server — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.

## Recommendation

If NanoBot is supposed to remember things durably, pick MCP. If it's just a chat shell,
`/v1` is enough to get moving.
