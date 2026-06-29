# Metronix MCP — primary & only memory source
You are a Hermes Agent with the Metronix MCP server registered and active (run
prompt 1 first, then restart). Run this ONCE.
Prompt 1 left a `metronix-config` block in your SOUL.md with the OPTIONAL wording;
this prompt upgrades it to mandatory. If it already has the mandatory wording, just
verify and report.

## Parameters
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID   = {{AGENT_UUID}}

## 0. Check parameters first
If either value above is still a {{...}} placeholder or empty STOP and try to find those values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Example: MTRNIX
- AGENT_UUID — any stable unique id for this agent, provided by the user; the user
  can make one up, or create it via POST /api/v1/agents / the UI. You do NOT create
  it. Example: a3c98413c3684a0992ac0e007b93f410
Wait for the user's answers before continuing.

## 1. Memory policy
Until now (after prompt 1) using Metronix memory was optional. This prompt makes it
mandatory: all durable knowledge lives in Metronix, NOT in Hermes' built-in files.
- The routing rule lives in `SOUL.md` (prompt 1 created it; step 3 below upgrades
  it), which Hermes loads on EVERY call — so the agent goes straight to Metronix
  with no extra lookup hop.
- Do NOT wipe or edit `~/.hermes/memories/MEMORY.md` or `USER.md` here. Migrating
  their existing content is a separate prompt (prompt 3).
- Metronix memory is classified by `kind`:
  - kind="fact" — durable factual statements ("user works at Acme")
  - kind="preference" — user preferences ("respond in Russian"). Auto-injected
    into prompts without retrieval — pin anything truly persistent here.
  - kind="pinned" — explicit instructions the user marked must-not-vanish.

## 2. Tools you have on Metronix
Search/document (workspace_id only):
`metronix_search`, `metronix_search_fast`, `metronix_get`, `metronix_store`,
`metronix_status`, `metronix_sync`.
Memory (workspace_id + agent_id BOTH required):
`metronix_memory_store`, `metronix_memory_search`, `metronix_memory_get_context`,
`metronix_memory_list`, `metronix_memory_update`, `metronix_memory_delete`,
`metronix_memory_batch_store`, `metronix_memory_review_list`,
`metronix_memory_review_resolve`. Run `/tools` for full schemas.
ALWAYS pass workspace_id (and agent_id for memory tools) explicitly — defaults
will not add them for you.

## 3. Upgrade the routing rule to mandatory (SOUL.md)
Edit the LIVE SOUL.md that Hermes actually loads — typically
`/root/.hermes/SOUL.md` when Hermes runs as root, otherwise `~/.hermes/SOUL.md`
(expand `~` to the home of the user Hermes runs as). Do NOT edit any backup or
copy of it (e.g. `SOUL.md.bak`, `SOUL.backup`, dated copies, files under a
`backups/` dir) — those are not loaded and editing them does nothing.

Prompt 1 wrote a `metronix-config` block with the OPTIONAL wording. Find that
block and REPLACE its body with the mandatory rule below, leaving the agent's
persona and everything else in the file intact. If the block isn't there (prompt 1
was skipped), APPEND it at the END of the file:

    --- metronix-config ---
    Durable memory lives in Metronix MCP. ALWAYS use the metronix_memory_*
    tools for it, with workspace_id="{{DEFAULT_WORKSPACE_ID}}" and
    agent_id="{{AGENT_UUID}}". Classify by kind:
    fact (default) | preference (auto-injected) | pinned (must-not-vanish).
    Do NOT use Hermes' built-in memory files for new durable knowledge, and do
    NOT silently fall back to them. If Metronix is unreachable, say so to the
    user instead of storing durable knowledge locally.
    --- end metronix-config ---

Do NOT touch `~/.hermes/memories/MEMORY.md` or `~/.hermes/memories/USER.md` —
leave their existing content exactly as it is.

## 4. Verify
- `metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")` — KB connectivity
- `metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
  agent_id="{{AGENT_UUID}}", limit=5)` — memory channel reachable
- confirm the live SOUL.md `metronix-config` block now has the mandatory wording
  AND that all of its pre-existing persona content is still present and unchanged

## Report format
- SOUL.md: routing rule upgraded to mandatory; existing persona preserved
- Verify: status ok, memory channel reachable
- Next step: run prompt 3 if this agent has prior memory to migrate
