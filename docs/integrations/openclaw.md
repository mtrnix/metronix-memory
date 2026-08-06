# OpenClaw

> **MCP authentication mode:** The installer and examples below target local
> `AUTH_ENABLED=false` and use `METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, put
> a user JWT in the same Bearer header; the shared key is ignored.

OpenClaw connects to Metronix through MCP.

## Recommended mode

Use Metronix Memory as a remote, Streamable-HTTP MCP server.

## What you need

- Metronix Memory running locally or remotely
- `METRONIX_MCP_API_KEY` from the Metronix Memory `.env`
- a stable OpenClaw agent id
- a workspace id such as `MTRNIX`

## Connection values

```text
URL:            http://localhost:8000/mcp
# = metronix-full-api container (metronix-core:8000/mcp from Docker network)
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-agent-id>   # same id as agent_id in memory tools; match Metronix Console agent UUID
```

## Automated setup

`./install.sh --connect-openclaw -y` (or the interactive `connect_agent` prompt during a
normal install — choose option 4, "OpenClaw") registers Metronix as an MCP server via
OpenClaw's own CLI and appends an availability note to OpenClaw's persona file. It never
hand-edits `openclaw.json` — it shells out to `openclaw mcp set`, so the file's own JSON5
formatting (comments, trailing commas) is preserved. The filled setup prompts always land
in `metronix-openclaw-setup/` (gitignored).

## Manual setup

Where the files live:

| File | Path | Purpose |
|---|---|---|
| MCP server config | `~/.openclaw/openclaw.json` (JSON5) | Registers Metronix as an MCP server |
| Persona / always-on file | `~/.openclaw/workspace/SOUL.md` | Tells OpenClaw the workspace/agent id and that Metronix memory tools are available |

Register Metronix using OpenClaw's own CLI (recommended — it owns the JSON5 schema):

```bash
openclaw mcp set metronix '{"url":"http://localhost:8000/mcp","transport":"streamable-http","headers":{"Authorization":"Bearer <METRONIX_MCP_API_KEY>","X-Agent-Id":"<AGENT_UUID>"},"timeout":180,"connectTimeout":60}'
```

Verify with `openclaw mcp show metronix`.

> **Confidence note:** the config path, the `mcp set`/`show`/`unset` subcommands, the JSON
> payload schema, and the `SOUL.md` workspace path above were verified against a live
> OpenClaw **2026.6.11** install (originally sourced from `docs.openclaw.ai`). If a future
> OpenClaw release changes its CLI or config schema, `openclaw mcp --help` is the source of
> truth — re-check there before assuming this doc is stale. Older builds (2026.3.x) have no
> `mcp` subcommand at all — see Troubleshooting below.
>
> **Why the API key is inlined, not `${METRONIX_MCP_API_KEY}`:** OpenClaw has an open bug where
> `${VAR}` substitution does not expand inside HTTP MCP server `headers`
> ([openclaw/openclaw#71035](https://github.com/openclaw/openclaw/issues/71035)) — using it here
> would send the literal string `Bearer ${METRONIX_MCP_API_KEY}` and break authentication.

## Verify

Use these first:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_list(workspace_id="MTRNIX", agent_id="<stable-openclaw-agent-id>", limit=5)
```

Then store a small test fact and search for it.

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`), and check that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in OpenClaw.

**Tools not appearing after registration:** Restart OpenClaw after adding the MCP server — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`. If you reinstalled the Metronix stack (which rotates the key), just re-run `./install.sh --connect-openclaw -y` — it detects the stale key and re-registers with the current one.

**`openclaw mcp set` not found:** `install.sh --connect-openclaw` needs the `openclaw` CLI on `PATH`; without it, it falls back to writing a paste-ready prompt guide (`metronix-openclaw-setup/`) instead of editing your config.

**`openclaw mcp` reports "unknown command":** Your OpenClaw build predates `mcp` support. Run
`openclaw update` to check for a newer version (`openclaw update status`). Until then,
`install.sh --connect-openclaw` falls back to the paste-ready guide automatically.

## Notes

Metronix Memory gives OpenClaw a better memory and knowledge surface. It does not replace
every internal runtime abstraction OpenClaw may already have.
