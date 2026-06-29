# Codex

## Recommended mode

Use Metronix Memory through MCP.

## What you need

- Metronix Memory running
- `METRONIX_MCP_API_KEY`
- a stable Codex agent id
- a workspace id

## Connection values

```text
URL:            http://localhost:8000/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-codex-agent-id>
```

## Setup

Register Metronix Memory as an MCP server in Codex with the values above.

If your Codex surface prefers an OpenAI-compatible chat endpoint instead of MCP, you can
also use:

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

MCP is still the better fit if you want memory tools, source sync, and explicit search
tooling rather than just chat completions.

## Verify

Start with:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_search(workspace_id="MTRNIX", agent_id="<stable-codex-agent-id>", query="test")
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in Codex.

**Tools not appearing after registration:** Restart Codex after adding the MCP server — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.
