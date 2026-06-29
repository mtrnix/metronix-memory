# Metronix MCP — roll back to the state after prompt 1
You are a Hermes Agent with the Metronix MCP server registered and active. Run this
to UNDO prompt 2: flip durable memory from mandatory back to OPTIONAL, returning the
agent to exactly the state it was in right after prompt 1. The Metronix MCP server
stays registered and nothing you stored in Metronix (including anything migrated in
prompt 3) is touched — only the routing-rule wording is reverted. Run ONCE.

## Parameters
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID           = {{AGENT_UUID}}

## 0. Check parameters first
If either value above is still a {{...}} placeholder or empty, STOP and try to find those values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Example: MTRNIX
- AGENT_UUID — any stable unique id for this agent, provided by the user; the user
  can make one up, or create it via POST /api/v1/agents / the UI. You do NOT create
  it. Example: a3c98413c3684a0992ac0e007b93f410
Wait for the user's answers before continuing.

## 1. Downgrade the routing rule back to optional (SOUL.md)
Edit the LIVE SOUL.md that Hermes actually loads — typically `/root/.hermes/SOUL.md`
when Hermes runs as root, otherwise `~/.hermes/SOUL.md`. Do NOT edit any backup or
copy (e.g. `SOUL.md.bak`, dated copies, files under a `backups/` dir) — those are
not loaded.

Prompt 2 replaced the `metronix-config` block with the MANDATORY wording. Find that
block and REPLACE its body with the OPTIONAL rule below, leaving the agent's persona
and everything else in the file intact. If the block isn't there, APPEND it at the
END of the file:

    --- metronix-config ---
    Metronix MCP is available. workspace_id="{{DEFAULT_WORKSPACE_ID}}",
    agent_id="{{AGENT_UUID}}". You MAY use the metronix_* tools — knowledge search /
    RAG and memory. Using Metronix for durable memory is OPTIONAL at this stage;
    it is not yet your required store.
    --- end metronix-config ---

This reverts ONLY what prompt 2 changed (the routing-rule wording). It does NOT
remove the Metronix MCP server (that was prompt 1) and does NOT delete or move any
memory already stored in Metronix, including anything migrated in prompt 3 — that
data stays exactly where it is. Do NOT touch `~/.hermes/memories/MEMORY.md` or
`~/.hermes/memories/USER.md`.

## 2. Verify
- confirm the `metronix-config` block now has the OPTIONAL wording and that all
  pre-existing persona content is still present and unchanged
- `metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")` still works — the MCP
  server is left in place

## Report format
- Routing rule: downgraded to optional (prompt 2 reverted)
- Left intact: Metronix MCP server registration, all stored/migrated memory
- Next step: re-run prompt 2 to make Metronix mandatory again, if desired
