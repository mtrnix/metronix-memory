# Codex

## Recommended mode

Use Metatron through MCP.

## What you need

- Metatron running
- `METATRON_MCP_API_KEY`
- a stable Codex agent id
- a workspace id

## Connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-codex-agent-id>
```

## Setup

Register Metatron as an MCP server in Codex with the values above.

If your Codex surface prefers an OpenAI-compatible chat endpoint instead of MCP, you can
also use:

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

MCP is still the better fit if you want memory tools, source sync, and explicit search
tooling rather than just chat completions.

## Verify

Start with:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_search(workspace_id="MTRNIX", agent_id="<stable-codex-agent-id>", query="test")
```
