# Codex

## Recommended mode

Use Metronix Memory through MCP, registered directly in `config.toml`. Unlike
Claude Code, `codex mcp add` is **not** the primary path here: the CLI only
supports `--url` and `--bearer-token-env-var` (plus OAuth) — it has no flag
for custom headers, and Metronix requires an `X-Agent-Id` header in addition
to `Authorization`. So Metronix is registered by editing `config.toml`'s
`[mcp_servers.metronix]` table directly.

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

### Automatic (installer)

`./install.sh --connect-codex` (interactive, offered at the end of a normal
install) or `./install.sh --connect-codex -y` (non-interactive, requires an
existing `.env`) edits `config.toml` for you: a minimal, validated text
insert (never a full rewrite), backed up first. If it can't safely apply the
change (no `yq`/Docker to validate, or an unusual existing layout), it writes
ready-to-paste prompts to `metronix-codex-setup/` instead of touching your
files.

### By hand

Add a `[mcp_servers.metronix]` table to `~/.codex/config.toml` (user scope,
every project on this machine) or `<project>/.codex/config.toml` (project
scope — Codex also requires the project be marked "trusted" before it will
load that file):

```toml
[mcp_servers.metronix]
url = "http://localhost:8000/mcp"
http_headers = { "Authorization" = "Bearer <METRONIX_MCP_API_KEY>", "X-Agent-Id" = "<stable-codex-agent-id>" }
startup_timeout_sec = 10.0
tool_timeout_sec = 60.0
```

| Scope | Where it's stored | Use when |
|---|---|---|
| User (recommended) | `~/.codex/config.toml` | You want Metronix available in every project on this machine. |
| Project | `<project>/.codex/config.toml`, typically committed to git, and requires the project be marked "trusted" in Codex | You want to share the MCP server with your team via the repo. **Puts the Bearer token in version control — avoid unless the endpoint is not sensitive.** |

Append this table rather than replacing the whole file — don't touch any
other `[mcp_servers.*]` entries already present. Run `codex mcp list`
afterward to confirm `metronix` shows up (this works regardless of how the
entry was added).

### Agent-assisted setup

Codex has shell and file access, so it can edit `config.toml` itself. Use the
prompts in [`../../connecting_to_agent.md`](../../connecting_to_agent.md), or
the filled versions the installer writes to `metronix-codex-setup/`. Prompt 1
has Codex edit `config.toml` directly (there's no `codex mcp add ...`
self-invocation to suggest, for the same header-support reason as above);
prompt 2 records the memory policy in `AGENTS.md`.

**Restart Codex** after registering the MCP server — it loads MCP servers
only at startup.

## Verify

Start with:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_search(workspace_id="MTRNIX", agent_id="<stable-codex-agent-id>", query="test")
```

## OpenAI-compatible fallback

If your Codex surface prefers a chat endpoint instead of MCP, you can also use:

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

MCP is still the better fit if you want memory tools, source sync, and explicit search
tooling rather than just chat completions.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in Codex.

**Tools not appearing after registration:** Restart Codex after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.

**`codex mcp add` doesn't work for this:** That's expected — the CLI's `add` subcommand can't set the `X-Agent-Id` header Metronix requires. Edit `config.toml` directly (see above), or use `./install.sh --connect-codex`.

**Running Codex in WSL2/Docker:** Use `host.docker.internal` instead of `localhost` in the MCP URL if Metronix runs on the Windows host.

## Recommendation

Use one stable `X-Agent-Id` per long-lived Codex agent so memory history stays
under a single identity. Prefer user scope unless you specifically need to share the
MCP registration with a team via git (project scope).
