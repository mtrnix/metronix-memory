# OpenCode

## Recommended mode

Use Metronix Memory through MCP.

If OpenCode only needs chat completions, the OpenAI-compatible endpoint also works. But if
you want durable memory and explicit retrieval tools, MCP is the stronger integration.

## MCP connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-opencode-agent-id>
```

## OpenAI-compatible fallback

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

## Recommended setup flow

1. Start with MCP.
2. Verify `metatron_status`.
3. Verify `metatron_memory_list`.
4. Only fall back to the OpenAI-compatible endpoint if OpenCode does not expose MCP cleanly.

## Why

OpenAI-compatible chat is easy, but MCP keeps search, memory, sync, and review explicit.
