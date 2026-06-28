# Claude Code

## Recommended mode

Use Metatron through MCP.

## What you need

- Metatron running
- `METATRON_MCP_API_KEY`
- a stable Claude Code agent id
- a workspace id

## Connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-claude-code-agent-id>
```

## Setup

Add Metatron as an MCP server in Claude Code using the values above.

Claude Code's exact config surface may vary by version, but the required Metatron side is
simple and stable: MCP URL plus the two headers.

If Claude Code supports agent-assisted MCP setup, use the prompt from:

- [`../../connecting_to_agent.md`](../../connecting_to_agent.md)

## Verify

Run:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<stable-claude-code-agent-id>", limit=5)
```

## Recommendation

Use one stable `X-Agent-Id` per long-lived Claude Code agent. Otherwise memory history gets
fragmented into a tiny graveyard of almost-identical identities.
