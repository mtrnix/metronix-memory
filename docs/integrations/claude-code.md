# Claude Code

## Recommended mode

Use Metronix Memory through MCP.

## What you need

- Metronix Memory running
- `METRONIX_MCP_API_KEY`
- a stable Claude Code agent id
- a workspace id

## Connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-claude-code-agent-id>
```

## Setup

Add Metronix Memory as an MCP server in Claude Code using the values above.

Claude Code's exact config surface may vary by version, but the required Metronix Memory side is
simple and stable: MCP URL plus the two headers.

If Claude Code supports agent-assisted MCP setup, use the prompt from:

- [`../../connecting_to_agent.md`](../../connecting_to_agent.md)

## Verify

Run:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_list(workspace_id="MTRNIX", agent_id="<stable-claude-code-agent-id>", limit=5)
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8001/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in Claude Code.

**Tools not appearing after registration:** Restart Claude Code after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.

## Recommendation

Use one stable `X-Agent-Id` per long-lived Claude Code agent so memory history stays
under a single identity.
