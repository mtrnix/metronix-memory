# Metronix MCP — primary & only memory source
You are a Claude Code instance with the Metronix MCP server registered and
active (run prompt 1 first, then restart). Run this ONCE.
Prompt 1 left no memory-policy record; this prompt checks memory read **and
write** authorization first, then creates the mandatory-wording record only if
both checks pass. If a `metronix-config` block already exists with the mandatory
wording, skip step 4 (the file edit) — but still run the preflight in step 3
before verifying and reporting; a working credential can go stale between runs,
so re-running must re-prove the memory channel, not assume it.

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
From now on, use Metronix memory as the durable knowledge store: all durable
knowledge lives in Metronix, NOT in ad-hoc local notes.
- The routing rule lives in `CLAUDE.md` (step 4 below writes it), which Claude
  Code loads at the start of every session — so you go straight to Metronix
  with no extra lookup hop.
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
skipped because the `metronix-config` block already has the mandatory
wording — never jump straight from step 0 to step 5 on a re-run.

The rule this prompt installs routes every durable write through
`metronix_memory_store`, so the preflight has to prove **write** access, not
just read. Run both checks below; proceed to step 4 only if **both** pass.

### 3a. Read check
Call `metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
agent_id="{{AGENT_UUID}}", limit=1)`.

Pass: a successfully-parsed response that contains **no** `error` field at
all. An empty `records` list (no memory stored yet) is a pass, not a denial.

### 3b. Write check — non-mutating
Call `metronix_memory_delete(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
agent_id="{{AGENT_UUID}}", record_id="metronix-preflight-probe-<RANDOM>")`,
where `<RANDOM>` is 16+ random hex characters you generate now.

This deletes nothing: the id cannot match a real record, so the call clears
the same write-authorization gate `metronix_memory_store` will hit and then
stops at "not found". Pass: a response whose **`error.code` is exactly
`DOCUMENT_NOT_FOUND`** — write access is confirmed and the probe id simply
matched nothing.

### If 3a or 3b fails
STOP. Do NOT edit CLAUDE.md. Report exactly what happened to the user — the
failing check, the tool name, and whatever status code / error code /
message the response carried — instead of proceeding. Only the explicit
"Pass" above counts as success; treat everything else as a failure,
including:
- `error.code == "AUTH_REQUIRED"` (transport authenticated but no memory
  principal, or a principal with read but not write)
- 3b returning any `error.code` other than `DOCUMENT_NOT_FOUND`, or 3a
  returning any `error` field at all (`WORKSPACE_NOT_FOUND`,
  `INVALID_PARAMS`, `INTERNAL_ERROR`, …) — do not special-case one code as
  the sole real failure
- a non-2xx HTTP response, or one with no parseable JSON body at all (e.g. a
  plain HTTP 401 whose body is `{"detail": ...}` and carries no `error`
  field — still a failure, not a pass by omission)
- `metronix_memory_list` or `metronix_memory_delete` not being available as
  a tool in this session
- 3b unexpectedly reporting that a record was deleted

If either check failed with `error.code == "AUTH_REQUIRED"`, use this
recovery path: the credential configured in prompt 1 (`METRONIX_MCP_API_KEY`)
authenticates MCP transport only and does not authorize memory tools. They
need to obtain a personal API key (`mtk_…`) or a user JWT (see prompt 1's
credential note), update the MCP server registration written in prompt 1 to
use it instead of the shared key, restart Claude Code, then re-run this
prompt. Do not attempt to self-provision a credential or otherwise bypass
this check.

For every other failure, report the tool name and whatever status code /
error code / message the response carried, then stop there — do not guess a
cause or improvise a different recovery path.

## 4. Write the routing rule (CLAUDE.md)
Only reached after the preflight above succeeds. Pick the file that matches
the scope prompt 1 registered the MCP server at:
- `--scope user` → `~/.claude/CLAUDE.md` (create the file/dir if missing)
- `--scope project` or `--scope local` → `./CLAUDE.md` in the project root

Do NOT wipe or rewrite existing content in that file; just APPEND this block at
the END, clearly delimited. If a `metronix-config` block is already there (e.g.
from a previous run), update it in place instead of appending a second copy:

    --- metronix-config ---
    Durable memory lives in Metronix MCP. ALWAYS use the metronix_memory_*
    tools for it, with workspace_id="{{DEFAULT_WORKSPACE_ID}}" and
    agent_id="{{AGENT_UUID}}". Classify by kind:
    fact (default) | preference (auto-injected) | pinned (must-not-vanish).
    Do NOT use local scratch files or notes for new durable knowledge, and do
    NOT silently fall back to them. If Metronix is unreachable, say so to the
    user instead of storing durable knowledge locally.
    --- end metronix-config ---

## 5. Verify
- `metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")` — KB connectivity
- confirm the `metronix-config` block in CLAUDE.md has the mandatory wording
  AND that all pre-existing content in the file is still present and unchanged

## Report format
- CLAUDE.md: routing rule written/upgraded at <path> (or: left unchanged —
  already mandatory on this run); existing content preserved
- Preflight (step 3): read + write both authorized — metronix_memory_list
  returned no `error` field; the metronix_memory_delete probe returned
  `DOCUMENT_NOT_FOUND`
- Verify (step 5): metronix_status ok
- Next step: run prompt 3 if this agent has prior memory to migrate
