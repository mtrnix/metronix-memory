# LangChain

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` MCP clients use a user JWT instead;
> the shared key is ignored.

## Recommended mode

Use Metronix Memory's OpenAI-compatible API for chat, or call REST/MCP directly for advanced
memory workflows.

## Chat setup

Use:

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

This gives LangChain a RAG-backed chat surface over your Metronix Memory workspace.

## When to use MCP too

Use MCP if you want explicit tools for:

- memory store and search
- source sync
- status checks
- low-level retrieval flows

## Verify

After setup, confirm the connection works:

1. Point your `ChatOpenAI` (or equivalent) client at `http://localhost:8000/v1` with model `metronix-rag-<workspace_id>`.
2. Send a test message and confirm a grounded response is returned.
3. If using MCP, call `metronix_status(workspace_id="MTRNIX")` and confirm a status response.

If the endpoint is unreachable, run `curl http://localhost:8000/health` to check the stack.

## Troubleshooting

**API endpoint unreachable:** Verify the stack is running (`curl http://localhost:8000/health`) and that `METRONIX_OPENAI_COMPAT_KEY` in your `.env` is set and non-empty.

**MCP tools not available:** If using MCP, check that `METRONIX_MCP_API_KEY` is set and the `Authorization: Bearer <key>` header is included in all MCP requests.

**Authentication errors:** Confirm the API key passed to LangChain matches `METRONIX_OPENAI_COMPAT_KEY` in `.env`.

## Recommendation

For a first integration:

1. Use the OpenAI-compatible endpoint for `ChatOpenAI` style flows.
2. Add MCP or REST later if you need durable memory control outside chat.

That keeps the first version simple and avoids building a tiny distributed system by accident.
