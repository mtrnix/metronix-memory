# LangChain

## Recommended mode

Use Metatron's OpenAI-compatible API for chat, or call REST/MCP directly for advanced
memory workflows.

## Chat setup

Use:

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

This gives LangChain a RAG-backed chat surface over your Metatron workspace.

## When to use MCP too

Use MCP if you want explicit tools for:

- memory store and search
- source sync
- status checks
- low-level retrieval flows

## Recommendation

For a first integration:

1. Use the OpenAI-compatible endpoint for `ChatOpenAI` style flows.
2. Add MCP or REST later if you need durable memory control outside chat.

That keeps the first version simple and avoids building a tiny distributed system by accident.
