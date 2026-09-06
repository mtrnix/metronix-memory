# Metronix MCP — primary & only memory source
You are a Hermes Agent with the Metronix MCP server registered and active (run
prompt 1 first, then restart). Run this ONCE.
Prompt 1 left a `metronix-config` block in your SOUL.md with the OPTIONAL wording;
this prompt checks memory authorization first, then upgrades it to mandatory only
if that check passes. If it already has the mandatory wording, skip step 4 (the
file edit) — but still run the preflight in step 3 before verifying and
reporting; a working credential can go stale between runs, so re-running must
re-prove the memory channel, not assume it.

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
- The routing rule lives in `SOUL.md` (prompt 1 created it; step 4 below upgrades
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
`metronix_search_fast`, `metronix_get`, `metronix_store`,
`metronix_status`, `metronix_sync`.
Memory (workspace_id + agent_id BOTH required):
`metronix_memory_store`, `metronix_memory_search`, `metronix_memory_get_context`,
`metronix_memory_list`, `metronix_memory_update`, `metronix_memory_delete`,
`metronix_memory_batch_store`, `metronix_memory_review_list`,
`metronix_memory_review_resolve`. Run `/tools` for full schemas.
ALWAYS pass workspace_id (and agent_id for memory tools) explicitly — defaults
will not add them for you.

## 3. Preflight — verify the memory channel before writing anything
Run this step every time this prompt runs, including when step 4 will be
skipped because the block already has the mandatory wording — never jump
straight from step 0 to step 5 on a re-run.

Call `metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
agent_id="{{AGENT_UUID}}", limit=1)`.

Success criterion (fail-closed): proceed to step 4 ONLY if the call returns a
successfully-parsed response that contains **no** `error` field at all. An
empty `records` list (no memory stored yet) is success, not a failure — do
not treat "no records" as denial.

Everything else is a failure. STOP. Do NOT edit SOUL.md. Report exactly what
happened to the user instead of proceeding — this covers:
- a response with an `error` field, whatever its `error.code` is
  (`AUTH_REQUIRED`, `WORKSPACE_NOT_FOUND`, `INVALID_PARAMS`,
  `INTERNAL_ERROR`, or any other code — only "no `error` field" counts as
  success; do not special-case `AUTH_REQUIRED` as the sole failure)
- a non-2xx HTTP response, or one with no parseable JSON body at all (e.g. a
  plain HTTP 401 whose body is `{"detail": ...}` and carries no `error`
  field — that is still a failure, not a pass by omission)
- `metronix_memory_list` not being available as a tool in this session

If `error.code == "AUTH_REQUIRED"` specifically, use this recovery path: the
credential configured in prompt 1 (`METRONIX_MCP_API_KEY`) authenticates MCP
transport only and does not authorize memory tools. They need to obtain a
personal API key (`mtk_…`) or a user JWT (see prompt 1's credential note),
update the `Authorization` header under `mcp_servers.metronix` in the config
written in prompt 1 to use it instead of the shared key, restart Hermes, then
re-run this prompt. Do not attempt to self-provision a credential or
otherwise bypass this check.

For every other failure above, report the tool name and whatever status
code / error code / message the response carried, then stop there — do not
guess a cause or improvise a different recovery path.

## 4. Upgrade the routing rule to mandatory (SOUL.md)
Only reached after the preflight above succeeds. Edit the LIVE SOUL.md that
Hermes actually loads — typically `/root/.hermes/SOUL.md` when Hermes runs as
root, otherwise `~/.hermes/SOUL.md` (expand `~` to the home of the user Hermes
runs as). Do NOT edit any backup or copy of it (e.g. `SOUL.md.bak`,
`SOUL.backup`, dated copies, files under a `backups/` dir) — those are not
loaded and editing them does nothing.

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

## 5. Verify
- `metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")` — KB connectivity
- confirm the live SOUL.md `metronix-config` block now has the mandatory wording
  AND that all of its pre-existing persona content is still present and unchanged

## Report format
- SOUL.md: routing rule upgraded to mandatory (or: left unchanged — already
  mandatory on this run); existing persona preserved
- Preflight (step 3): memory channel reachable — metronix_memory_list
  returned no `error` field
- Verify (step 5): metronix_status ok
- Next step: run prompt 3 if this agent has prior memory to migrate
