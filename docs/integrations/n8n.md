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
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

## REST base

```text
http://localhost:8001/api/v1
```

## When to use MCP

Use MCP only if your n8n flow or plugin stack already supports external MCP servers cleanly.
Otherwise HTTP is the pragmatic path.

## Recommendation

In n8n, a stable HTTP workflow is usually easier to maintain than an MCP setup that your
stack does not support natively.
