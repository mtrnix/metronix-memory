# n8n

## Recommended mode

Use Metronix Memory through HTTP nodes first.

That usually means:

- OpenAI-compatible API for chat
- REST API for uploads, memory inspection, or admin workflows

## Chat setup

Use an HTTP Request node or OpenAI-compatible node with:

```text
Base URL: http://localhost:8001/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

## REST base

```text
http://localhost:8001/api/v1
```

## When to use MCP

Use MCP only if your n8n flow or plugin stack already supports external MCP servers cleanly.
Otherwise HTTP is the pragmatic path.

## Verify

After setup, confirm the connection works:

1. In your n8n workflow, add an HTTP Request node pointing to `http://localhost:8001/health`.
2. Execute the node and confirm a 200 OK response.
3. Then test the chat endpoint with a request to `http://localhost:8001/v1/chat/completions`.

## Troubleshooting

**HTTP node request fails:** Verify the stack is running (`curl http://localhost:8001/health`) and that `METRONIX_OPENAI_COMPAT_KEY` is set in your `.env`.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header in the n8n node matches `METRONIX_OPENAI_COMPAT_KEY` in `.env`.

**MCP server not responding:** If using MCP, verify `METRONIX_MCP_API_KEY` is set and the MCP node is configured with the correct URL (`http://localhost:8001/mcp`) and headers.

## Recommendation

In n8n, a stable HTTP workflow is usually easier to maintain than an MCP setup that your
stack does not support natively.
