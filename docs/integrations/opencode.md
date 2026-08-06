# OpenCode

> **MCP authentication mode:** The example targets local `AUTH_ENABLED=false` and uses
> `METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, put a user JWT in the same Bearer
> header; the shared key is ignored.

## Recommended mode

Use Metronix Memory through MCP.

If OpenCode only needs chat completions, the OpenAI-compatible endpoint also works. But if
you want durable memory and explicit retrieval tools, MCP is the stronger integration.

## MCP connection values

```text
URL:            http://localhost:8000/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-opencode-agent-id>
```

## OpenAI-compatible fallback

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

## Recommended setup flow

1. Start with MCP.
2. Verify `metronix_status`.
3. Verify `metronix_memory_list`.
4. Only fall back to the OpenAI-compatible endpoint if OpenCode does not expose MCP cleanly.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in OpenCode.

**Tools not appearing after registration:** Restart OpenCode after adding the MCP server — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.

## Why

OpenAI-compatible chat is easy, but MCP keeps search, memory, sync, and review explicit.
