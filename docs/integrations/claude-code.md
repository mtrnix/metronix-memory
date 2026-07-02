# Claude Code

## Recommended mode

Use Metronix Memory through MCP, registered with the `claude` CLI's built-in
`claude mcp add` command. Claude Code manages its own MCP config
(`~/.claude.json`, or `.mcp.json` for project/local scope) — there is no file
you need to hand-edit in the common case.

## What you need

- Metronix Memory running
- `METRONIX_MCP_API_KEY`
- a stable Claude Code agent id
- a workspace id

## Connection values

```text
URL:            http://localhost:8000/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-claude-code-agent-id>
```

## Setup

### Automatic (installer)

`./install.sh --connect-claude` (interactive, offered at the end of a normal
install) or `./install.sh --connect-claude -y` (non-interactive, requires an
existing `.env`) runs `claude mcp add` for you. If the `claude` CLI isn't on
PATH, it falls back to a validated, backed-up edit of `~/.claude.json` via
`jq`. Either way, if it can't safely apply the change it writes ready-to-paste
prompts to `metronix-claude-code-setup/` instead of touching your files.

### By hand

```bash
claude mcp add --transport http --scope user metronix \
  http://localhost:8000/mcp \
  --header "Authorization: Bearer <METRONIX_MCP_API_KEY>" \
  --header "X-Agent-Id: <stable-claude-code-agent-id>"
```

`--scope` controls where the server is registered:

| Scope | Where it's stored | Use when |
|---|---|---|
| `user` (recommended) | `~/.claude.json`, top-level | You want Metronix available in every project on this machine. |
| `project` | `./.mcp.json`, typically committed to git | You want to share the MCP server with your team via the repo. **Puts the Bearer token in version control — avoid unless the endpoint is not sensitive, or use a secrets-injection workaround.** |
| `local` | `~/.claude.json`, scoped to this project only | Private to you, this project only. |

Run `claude mcp list` afterward to confirm `metronix` shows as connected.

If the `claude` CLI is unavailable, add the entry to `~/.claude.json` directly
(back it up first):

```json
{
  "mcpServers": {
    "metronix": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <METRONIX_MCP_API_KEY>",
        "X-Agent-Id": "<stable-claude-code-agent-id>"
      }
    }
  }
}
```

Merge this into the existing `mcpServers` object — don't overwrite unrelated
keys (session history, project state, etc.) elsewhere in the file.

### Agent-assisted setup

Claude Code has shell access, so it can run the setup itself. Use the prompts
in [`../../connecting_to_agent.md`](../../connecting_to_agent.md), or the
filled versions the installer writes to `metronix-claude-code-setup/`. Prompt 1
has Claude Code run `claude mcp add` (or edit `~/.claude.json` as a fallback);
prompt 2 records the memory policy in `CLAUDE.md`.

**Restart Claude Code** after registering the MCP server — it loads MCP
servers only at startup.

## Verify

Run:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_list(workspace_id="MTRNIX", agent_id="<stable-claude-code-agent-id>", limit=5)
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in Claude Code.

**Tools not appearing after registration:** Restart Claude Code after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.

**`claude mcp add` reports metronix already exists:** Remove it first with `claude mcp remove metronix`, or edit the entry directly in `~/.claude.json` / `.mcp.json`.

**Running Claude Code in WSL2/Docker:** Use `host.docker.internal` instead of `localhost` in the MCP URL if Metronix runs on the Windows host.

## Recommendation

Use one stable `X-Agent-Id` per long-lived Claude Code agent so memory history stays
under a single identity. Prefer `--scope user` unless you specifically need to share the
MCP registration with a team via git (`--scope project`).
