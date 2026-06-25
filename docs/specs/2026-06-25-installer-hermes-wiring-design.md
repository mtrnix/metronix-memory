# Installer — Hermes agent wiring

**Date:** 2026-06-25
**Status:** Design (pending review)
**Scope:** `install.sh` only. v1 supports the **Hermes** agent exclusively.

## 1. Problem

After `install.sh` brings the stack up, connecting an external agent (e.g. Hermes)
to Metronix over MCP is a fully manual, multi-step task: the user reads
`docs/integrations/hermes.md`, copies four values into prompts, and pastes them into
Hermes. The installer already holds most of those values at the end of a run
(`METRONIX_MCP_API_KEY`, `DEFAULT_WORKSPACE_ID`, the MCP URL), so it is in a good
position to do the wiring — or at least hand the user a fully pre-filled prompt.

## 2. Goal

At the end of any successful install (both `memory` and `answers` modes — agent
access is orthogonal to whether Metronix also generates answers itself), and via a
standalone flag, offer to connect Hermes to Metronix with zero extra questions and a
single confirmation, with a safe pre-filled-prompt fallback for every other case.

## 3. Scope boundary — what we write vs. don't

The installer automates **only "Prompt 1" of `docs/integrations/hermes.md`** — the
*connection*:

1. `~/.hermes/config.yaml` — add/update the `mcp_servers.metronix` block (registers
   the MCP server: URL + `Authorization: Bearer` + `X-Agent-Id`).
2. `~/.hermes/SOUL.md` — add/update a delimited `--- metronix-config ---` block with
   the **optional** wording (tells Hermes the `workspace_id` / `agent_id` to pass and
   that the `metronix_*` tools exist; using Metronix for memory stays optional).

**Explicitly NOT done** (left to the user via the existing pasted prompts):

- Prompt 2 — making Metronix the *mandatory / only* durable-memory store (a memory
  *policy* decision).
- Prompt 3 — migrating existing Hermes memory.

Principle: the installer wires the **plumbing**; the user decides **policy**.

## 4. Values and provenance (zero extra questions)

| Value | Source | Prompted? |
|---|---|---|
| `MCP_API_KEY` | `.env` → `METRONIX_MCP_API_KEY` | no |
| `WORKSPACE_ID` | `.env` → `DEFAULT_WORKSPACE_ID` (default `MTRNIX`) | no |
| `AGENT_UUID` | reuse existing `X-Agent-Id` from `config.yaml` if present, else generate (`uuidgen`, fallback `openssl rand -hex 16`, fallback `/dev/urandom`); override via `--agent-id` | no |
| `METRONIX_URL` | default `http://localhost:8000/mcp`; override via `--metronix-url` | no (print a note: use `host.docker.internal` if Hermes runs in WSL2/Docker against a host-run Metronix) |

**Idempotency:** re-running reuses the existing `X-Agent-Id` (so a re-run never
orphans memories under a new id), updates the `config.yaml` block in place, and
replaces the `SOUL.md` delimited block in place — never duplicates either.

## 5. Flow

Runs at the end of a successful install (memory **or** answers mode), and standalone
via `./install.sh --wire-hermes` (which skips the stack build and only wires against
an existing `.env`).

```
Stack healthy (any mode)  /  ./install.sh --wire-hermes
        │
        ├─ ~/.hermes/config.yaml present?
        │        │
        │        ├─ YES → "Wire Metronix into Hermes automatically? [Y/n]"
        │        │        ├─ Yes → auto-edit config.yaml + SOUL.md
        │        │        │         (backup + diff + confirm; see §6).
        │        │        │         If yq is missing → fall back to the filled prompt.
        │        │        └─ No  → emit the ready-filled Hermes setup prompt (§7).
        │        │
        │        └─ NO  → emit the ready-filled Hermes setup prompt (§7),
        │                  noting "install Hermes, then apply this".
```

The **ready-filled prompt is the universal fallback** — used on decline, on a missing
`~/.hermes`, and when `yq` is unavailable.

**`-y` / non-interactive:** the agent config is touched **only** when `--wire-hermes`
is passed explicitly. A bare `-y` install never edits `~/.hermes` silently; it still
emits the filled prompt file as a handoff.

## 6. Mechanics and safety

- **Detect:** presence of `~/.hermes/config.yaml` (or the `~/.hermes/` dir).
- **`config.yaml` (YAML):** merge `.mcp_servers.metronix = {…}` with **`yq`**
  (mikefarah) so the rest of the file is preserved. If `yq` is absent, do **not**
  hand-edit YAML from bash — fall back to the filled prompt (§7).
- **`SOUL.md` (plain text):** the `--- metronix-config --- … --- end metronix-config ---`
  block is delimited text, no parser needed: if the markers exist, replace the body
  between them; otherwise append the block at end of file. Persona content is never
  touched.
- **Per-edit safety:** copy the target to `<file>.bak-<timestamp>` → show a `diff` of
  the proposed change → prompt `[Y/n]` → write only on yes. (Timestamp from `date`;
  acceptable here — this is the installer, not a workflow script.)

## 7. Templates (DRY) and the filled prompt

Two templates live **embedded in `install.sh`** (not read from the docs at runtime —
that is fragile), each with `{{METRONIX_URL}}`, `{{MCP_API_KEY}}`, `{{AGENT_UUID}}`,
`{{WORKSPACE_ID}}` placeholders:

- the `config.yaml` `mcp_servers.metronix` block;
- the `SOUL.md` `--- metronix-config ---` (optional-wording) block.

Real values are substituted **once**. The result is then either:

- **applied** (auto-edit path, §6), or
- **written** to `./metronix-hermes-setup.md` (a file is easier to copy than a wall of
  terminal text), and the path is printed. The file contains the filled `config.yaml`
  block, the filled `SOUL.md` block, and short "paste into Hermes / restart" steps.

A comment by the templates notes: **keep in sync with `docs/integrations/hermes.md`.**

## 8. After wiring

Print: restart Hermes (`/quit`, then `hermes`) so it loads the new MCP client; and
that Prompt 2 (mandatory memory) / Prompt 3 (migration) from
`docs/integrations/hermes.md` are the user's deliberate next steps.

## 9. New flags

- `--wire-hermes` — run only the Hermes wiring against an existing `.env` (no build).
- `--agent-id <id>` — override the generated `X-Agent-Id`.
- `--metronix-url <url>` — override the default MCP URL.

## 10. Testing

Sandboxed bash tests under `tests/installer/` (no docker, mirroring the existing
harness), covering:

- detect-present + accept → `config.yaml` gains a correct `mcp_servers.metronix`;
  `SOUL.md` gains the delimited block; values pulled from a fixture `.env`.
- idempotency: a second run reuses the same `X-Agent-Id` and does not duplicate blocks.
- detect-present + decline → no file edits; `metronix-hermes-setup.md` written.
- detect-absent → no `~/.hermes` touched; `metronix-hermes-setup.md` written.
- `yq` missing (stub it out) → no `config.yaml` edit; falls back to the prompt file.
- `SOUL.md` with an existing `metronix-config` block → replaced in place, persona
  content above it intact.
- `-y` without `--wire-hermes` → `~/.hermes` untouched.

Tests must stub `$HOME`/the `~/.hermes` path into a temp dir so they never touch a
real Hermes install.

## 11. Risks / open items

- **`yq` availability** on user machines is uncertain; the prompt-file fallback covers
  its absence without hand-editing YAML.
- **`METRONIX_URL` correctness** when Hermes runs in WSL2/Docker against a host-run
  Metronix — we default to `localhost` and print the `host.docker.internal` note;
  full auto-detection is out of scope for v1.
- **Template drift** vs. `docs/integrations/hermes.md` — mitigated by the sync comment;
  a future step could generate the doc from the templates.
- v1 is **Hermes only**; the detect/template structure should be factored so Cursor,
  Claude Desktop, etc. can be added later without reworking the flow.
