# Metronix MCP — install as an MCP server
Authentication mode: this generated prompt targets local `AUTH_ENABLED=false` and uses
`METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, use a user JWT in the Bearer header;
the shared key is ignored.

You are a Claude Code instance with shell access. Run this ONCE per deployment.
If `metronix` already exists in `claude mcp list` with the correct URL, just
verify it and report — do not create a duplicate.

## Parameters
- METRONIX_URL = {{METRONIX_URL}}
- METRONIX_MCP_API_KEY  = {{METRONIX_MCP_API_KEY}}
- AGENT_UUID   = {{AGENT_UUID}}
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}

## 0. Check parameters first
If any value above is still a {{...}} placeholder or empty, STOP and try to find those values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- METRONIX_URL — Metronix MCP endpoint URL: server URL + /mcp. If Claude Code runs in
  WSL2/Docker and Metronix is on the Windows host, use host.docker.internal
  instead of localhost. Example: http://host.docker.internal:8000/mcp
- METRONIX_MCP_API_KEY — Bearer token for /mcp (server env var METRONIX_MCP_API_KEY; /mcp
  returns HTTP 401 without it; ask the Metronix admin if you don't have it).
  Example: the token from the Metronix deployment's .env
- AGENT_UUID — any stable unique id for this agent, provided by the user; the user
  can simply make one up, or create it via POST /api/v1/agents / the UI. You do NOT
  create it. Example: a3c98413c3684a0992ac0e007b93f410
- DEFAULT_WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Every metronix_* call (search/RAG and memory) needs it, which is why it is set
  now. Example: MTRNIX
Do NOT call POST /api/v1/agents (or otherwise hit the /api/v1/agents endpoint)
yourself to create an agent or obtain AGENT_UUID — registering the agent and its id
is the user's job, done out of band. If AGENT_UUID is missing, ask the user and
wait; never self-register.
Wait for the user's answers and fill them in before continuing.

## 1. Register Metronix as an MCP server
Run this yourself via your shell tool:

    claude mcp add --transport http --scope user metronix {{METRONIX_URL}} \
      --header "Authorization: Bearer {{METRONIX_MCP_API_KEY}}" \
      --header "X-Agent-Id: {{AGENT_UUID}}"

`--scope user` makes the server available in every project on this machine. If
the user asks for project-only sharing instead, use `--scope project` (this
writes `./.mcp.json`, which is typically committed to git — warn the user that
this puts the Bearer token in version control before doing it) or
`--scope local` (private, this project only).

If the `claude` CLI is unavailable or the command fails, fall back to editing
`~/.claude.json` directly: back it up first (copy to `~/.claude.json.bak-<timestamp>`),
then ensure it contains:

    {
      "mcpServers": {
        "metronix": {
          "type": "http",
          "url": "{{METRONIX_URL}}",
          "headers": {
            "Authorization": "Bearer {{METRONIX_MCP_API_KEY}}",
            "X-Agent-Id": "{{AGENT_UUID}}"
          }
        }
      }
    }

Merge this into the existing `mcpServers` object — do NOT overwrite unrelated
keys elsewhere in the file (session history, project state, etc.). Validate the
result is valid JSON before saving.

The `Authorization: Bearer` header is REQUIRED — the /mcp endpoint validates
METRONIX_MCP_API_KEY; without it every request is rejected with HTTP 401.
The `X-Agent-Id` header is REQUIRED too — without it, server-side observability
events for search and other no-agent_id-arg tools are dropped silently.

## 2. Test, then restart
Run `claude mcp list` from a shell to confirm `metronix` shows as connected. If
it errors or shows disconnected, fix and retry before continuing.
Then restart: Claude Code loads MCP servers only at startup, so the metronix_*
tools become available only in the NEXT session. Exit and run `claude` again.

## Report format
- MCP registration: ok / changes made (method: CLI / manual JSON edit)
- Scope used: user / project / local
- claude mcp list: connected / disconnected (error)
- Next step: restart the session, then run prompt 2 (memory source)
