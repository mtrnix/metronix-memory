# Hermes Agent Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `install.sh` step that connects the Hermes agent to Metronix over MCP — auto-editing `~/.hermes/config.yaml` + `~/.hermes/SOUL.md` when accepted, with a ready-filled prompt file as the universal fallback.

**Architecture:** Pure additions to the existing `install.sh` (bash). A set of small, sourceable functions (templates, value resolution, file merges) plus one orchestrator `wire_hermes()` called from `main()` after the stack is healthy (any mode) and from a standalone `--wire-hermes` path. YAML edits use `yq`; SOUL.md edits are plain delimited-block text. Everything keys off `$HOME` so tests can redirect it to a temp dir.

**Tech Stack:** bash (`set -euo pipefail`), `yq` (mikefarah v4, optional — graceful fallback), `uuidgen`/`openssl` for id generation, existing `info/ok/warn/err` helpers.

## Global Constraints

- Spec: `docs/specs/2026-06-25-installer-hermes-wiring-design.md`.
- v1 supports **Hermes only**; structure left extensible.
- Auto-edit covers **Prompt 1 only** (config.yaml `mcp_servers.metronix` + SOUL.md *optional-wording* `--- metronix-config ---` block). Never write Prompt 2/3 (memory policy / migration).
- Zero extra questions: `MCP_API_KEY`←`.env METRONIX_MCP_API_KEY`, `WORKSPACE_ID`←`.env DEFAULT_WORKSPACE_ID`, `AGENT_UUID`←reuse-or-generate, `METRONIX_URL`←default `http://localhost:8000/mcp`.
- Idempotent: reuse the existing `X-Agent-Id`; replace blocks in place, never duplicate.
- Every file edit: backup `<file>.bak-<ts>` → show `diff` → confirm. `-y --wire-hermes` applies without prompting (backup still made). Bare `-y` (no `--wire-hermes`) never touches `~/.hermes`.
- All `~/.hermes` access via `$HOME` (tests stub `HOME`).
- Commit-message rule (repo): no `Co-Authored-By` / "Generated with" trailers.
- Keep embedded templates in sync with `docs/integrations/hermes.md` (add a comment).
- Bash style: no `;`/`&&` chaining where a single command suffices; reuse existing `info/ok/warn/err`.

---

### Task 1: Flags, variables, and usage

**Files:**
- Modify: `install.sh` (variable block near top; `usage()`; `parse_args()`)
- Test: `tests/installer/test_wire_hermes.sh` (create)

**Interfaces:**
- Produces: globals `WIRE_HERMES` (bool, default false), `AGENT_ID` (string, default ""), `METRONIX_URL` (string, default ""). Flags `--wire-hermes`, `--agent-id <id>`, `--metronix-url <url>`.

- [ ] **Step 1: Write the failing test**

```bash
# tests/installer/test_wire_hermes.sh
#!/usr/bin/env bash
# Tests for the Hermes wiring in install.sh. Sandboxed; no docker, no real ~/.hermes.
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

echo "Task1: flags parse into globals"
out="$(bash -c "source '$INSTALL'; parse_args --wire-hermes --agent-id abc123 --metronix-url http://x:8000/mcp; echo \"\$WIRE_HERMES|\$AGENT_ID|\$METRONIX_URL\"")"
chk "flags parsed" "$out" "true|abc123|http://x:8000/mcp"
chk "usage lists --wire-hermes" "$(bash -c "source '$INSTALL'; usage" | grep -c -- '--wire-hermes')" "1"

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — `WIRE_HERMES`/`AGENT_ID`/`METRONIX_URL` unset, `--wire-hermes` unknown option.

- [ ] **Step 3: Add the variables** (in the variable block near the top of `install.sh`, after `RECONFIGURE=false`)

```bash
WIRE_HERMES=false    # run the Hermes wiring step (and, with -y, apply without prompt)
AGENT_ID=""          # override the generated X-Agent-Id (Hermes wiring)
METRONIX_URL=""      # override the MCP URL written into the agent config
```

- [ ] **Step 4: Add the flags** (in `parse_args()`, before the `--openwebui` line)

```bash
      --wire-hermes)   WIRE_HERMES=true; shift ;;
      --agent-id)      [[ $# -ge 2 ]] || { err "--agent-id requires a value"; exit 2; }; AGENT_ID="$2"; shift 2 ;;
      --metronix-url)  [[ $# -ge 2 ]] || { err "--metronix-url requires a value"; exit 2; }; METRONIX_URL="$2"; shift 2 ;;
```

- [ ] **Step 5: Document them in `usage()`** (append after the `--openwebui` line)

```
  --wire-hermes            Connect the Hermes agent to Metronix (edit ~/.hermes
                           config); with -y, apply without prompting. Also offered
                           interactively at the end of a normal install.
  --agent-id <id>          Override the generated agent id (X-Agent-Id)
  --metronix-url <url>     MCP URL written into the agent config
                           (default http://localhost:8000/mcp)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS (2 checks). Then `bash -n install.sh` → no output.

- [ ] **Step 7: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): add Hermes wiring flags (--wire-hermes/--agent-id/--metronix-url)"
```

---

### Task 2: Value resolution (agent id reuse/generate)

**Files:**
- Modify: `install.sh` (new helpers near `gen_secret`)
- Test: `tests/installer/test_wire_hermes.sh`

**Interfaces:**
- Produces:
  - `gen_agent_id() -> stdout` — 32 lowercase hex chars (no dashes).
  - `resolve_agent_id <config_path> -> stdout` — if `$AGENT_ID` set, echo it; else if the file has an `X-Agent-Id:` line, echo that value; else `gen_agent_id`.

- [ ] **Step 1: Write the failing test** (append to `test_wire_hermes.sh` before the TOTAL line)

```bash
echo "Task2: agent id resolution"
gid="$(bash -c "source '$INSTALL'; gen_agent_id")"
chk "gen_agent_id is 32 hex" "$(printf '%s' "$gid" | grep -cE '^[0-9a-f]{32}$')" "1"
d="$(mktemp -d)"; printf 'mcp_servers:\n  metronix:\n    headers:\n      X-Agent-Id: deadbeefdeadbeefdeadbeefdeadbeef\n' > "$d/config.yaml"
r="$(bash -c "source '$INSTALL'; AGENT_ID=''; resolve_agent_id '$d/config.yaml'")"
chk "reuses existing id" "$r" "deadbeefdeadbeefdeadbeefdeadbeef"
r2="$(bash -c "source '$INSTALL'; AGENT_ID='override999'; resolve_agent_id '$d/config.yaml'")"
chk "flag overrides reuse" "$r2" "override999"
r3="$(bash -c "source '$INSTALL'; AGENT_ID=''; resolve_agent_id '$d/none.yaml'")"
chk "generates when absent" "$(printf '%s' "$r3" | grep -cE '^[0-9a-f]{32}$')" "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — `gen_agent_id`/`resolve_agent_id` not defined.

- [ ] **Step 3: Add the helpers** (after `gen_fernet()` in `install.sh`)

```bash
# 32 lowercase hex chars — a stable, unique agent id for X-Agent-Id.
gen_agent_id() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr 'A-Z' 'a-z' | tr -d '-'
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# Resolve the agent id: explicit --agent-id wins; else reuse the X-Agent-Id
# already in the Hermes config (keeps memories under a stable id across re-runs);
# else generate a fresh one.
resolve_agent_id() {
  local config="$1" existing
  if [[ -n "$AGENT_ID" ]]; then printf '%s' "$AGENT_ID"; return 0; fi
  if [[ -f "$config" ]]; then
    existing="$(grep -E '^[[:space:]]*X-Agent-Id:' "$config" 2>/dev/null | head -1 | sed -E 's/.*X-Agent-Id:[[:space:]]*//' | tr -d '"' | tr -d '[:space:]')"
    if [[ -n "$existing" ]]; then printf '%s' "$existing"; return 0; fi
  fi
  gen_agent_id
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS (Task1 + Task2 checks). `bash -n install.sh` clean.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): resolve Hermes agent id (reuse existing, else generate)"
```

---

### Task 3: Templates (config block, SOUL block, prompt doc)

**Files:**
- Modify: `install.sh` (template functions)
- Test: `tests/installer/test_wire_hermes.sh`

**Interfaces:**
- Consumes: globals `H_URL`, `H_KEY`, `H_AGENT`, `H_WS` (set by the caller before invoking — the resolved values).
- Produces:
  - `hermes_config_block() -> stdout` — the YAML `mcp_servers.metronix` snippet.
  - `hermes_soul_block() -> stdout` — the `--- metronix-config ---` optional-wording block.
  - `hermes_prompt_doc() -> stdout` — a markdown handoff with both filled blocks + paste/restart steps.

- [ ] **Step 1: Write the failing test** (append before TOTAL)

```bash
echo "Task3: templates substitute values, no placeholders"
tpl="$(bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY123; H_AGENT=AID9; H_WS=MTRNIX; hermes_config_block; echo ---; hermes_soul_block; echo ---; hermes_prompt_doc")"
chk "no leftover {{ }}" "$(printf '%s' "$tpl" | grep -c '{{')" "0"
chk "config has url" "$(printf '%s' "$tpl" | grep -c 'http://h:8000/mcp')" "$(printf '%s' "$tpl" | grep -c 'http://h:8000/mcp')"
chk "config has bearer key" "$(printf '%s' "$tpl" | grep -c 'Bearer KEY123')" "1"
chk "config has agent header" "$(printf '%s' "$tpl" | grep -c 'X-Agent-Id: AID9')" "1"
chk "soul has workspace" "$(printf '%s' "$tpl" | grep -c 'workspace_id=\"MTRNIX\"')" "1"
chk "soul block delimited" "$(printf '%s' "$tpl" | grep -c -- '--- metronix-config ---')" "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — template functions not defined.

- [ ] **Step 3: Add the templates** (new section in `install.sh`, e.g. after `resolve_agent_id`)

```bash
# --- Hermes wiring templates -------------------------------------------------
# KEEP IN SYNC with docs/integrations/hermes.md (Prompt 1). These render the
# CONNECTION only (MCP registration + optional availability note); never the
# mandatory memory policy (Prompt 2) or migration (Prompt 3).
# Callers set H_URL / H_KEY / H_AGENT / H_WS before calling.

hermes_config_block() {
  cat <<EOF
  metronix:
    url: $H_URL
    headers:
      Authorization: "Bearer $H_KEY"
      X-Agent-Id: $H_AGENT
    timeout: 180
    connect_timeout: 60
EOF
}

hermes_soul_block() {
  cat <<EOF
--- metronix-config ---
Metronix MCP is available. workspace_id="$H_WS", agent_id="$H_AGENT".
You MAY use the metronix_* tools — knowledge search / RAG and memory. Using
Metronix for durable memory is OPTIONAL at this stage; it is not yet your
required store.
--- end metronix-config ---
EOF
}

hermes_prompt_doc() {
  cat <<EOF
# Connect Hermes to Metronix (paste-ready)

Two edits, then restart Hermes. This wires the CONNECTION only — making Metronix
your mandatory memory store is a separate, deliberate step (see Prompt 2 in
docs/integrations/hermes.md).

## 1. ~/.hermes/config.yaml — add under \`mcp_servers:\`
\`\`\`yaml
mcp_servers:
$(hermes_config_block)
\`\`\`

## 2. ~/.hermes/SOUL.md — append at the end
\`\`\`
$(hermes_soul_block)
\`\`\`

## 3. Restart
Run \`/quit\`, then \`hermes\` (Hermes loads its MCP client list at startup).
Optional next: Prompt 2 (make Metronix the only durable memory) and Prompt 3
(migrate existing memory) from docs/integrations/hermes.md.
EOF
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS. `bash -n install.sh` clean.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): embed Hermes config/SOUL/prompt templates"
```

---

### Task 4: SOUL.md block merge (append or replace in place)

**Files:**
- Modify: `install.sh`
- Test: `tests/installer/test_wire_hermes.sh`

**Interfaces:**
- Consumes: `hermes_soul_block` and globals it reads.
- Produces: `merge_soul_block <soul_file>` — ensures exactly one `--- metronix-config --- … --- end metronix-config ---` block: replace its body in place if the markers exist, else append the block (creating the file if missing). Never alters content outside the markers.

- [ ] **Step 1: Write the failing test** (append before TOTAL)

```bash
echo "Task4: SOUL.md append/replace"
d="$(mktemp -d)"; printf 'You are Persona.\nLine two.\n' > "$d/SOUL.md"
bash -c "source '$INSTALL'; H_URL=u; H_KEY=k; H_AGENT=a1; H_WS=MTRNIX; merge_soul_block '$d/SOUL.md'"
chk "persona preserved" "$(grep -c 'You are Persona.' "$d/SOUL.md")" "1"
chk "block appended once" "$(grep -c -- '--- metronix-config ---' "$d/SOUL.md")" "1"
# second run with a different agent id must REPLACE, not duplicate
bash -c "source '$INSTALL'; H_URL=u; H_KEY=k; H_AGENT=a2; H_WS=MTRNIX; merge_soul_block '$d/SOUL.md'"
chk "still single block" "$(grep -c -- '--- metronix-config ---' "$d/SOUL.md")" "1"
chk "id updated in place" "$(grep -c 'agent_id="a2"' "$d/SOUL.md")" "1"
chk "old id gone" "$(grep -c 'agent_id="a1"' "$d/SOUL.md")" "0"
chk "persona still there" "$(grep -c 'You are Persona.' "$d/SOUL.md")" "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — `merge_soul_block` not defined.

- [ ] **Step 3: Implement** (after the templates in `install.sh`)

```bash
# Ensure exactly one metronix-config block in the SOUL file. Replaces the body
# between the markers in place if present; otherwise appends. Content outside
# the markers is untouched.
merge_soul_block() {
  local soul="$1" tmp; tmp="$(mktemp)"
  if [[ -f "$soul" ]] && grep -qF -- '--- metronix-config ---' "$soul"; then
    # Drop the existing marker-delimited region, then append a fresh block.
    awk '
      /^--- metronix-config ---$/ { skip=1 }
      skip && /^--- end metronix-config ---$/ { skip=0; next }
      !skip { print }
    ' "$soul" > "$tmp"
    # strip a trailing blank line to keep spacing tidy, then append
    printf '\n' >> "$tmp"
    hermes_soul_block >> "$tmp"
    mv "$tmp" "$soul"
  else
    rm -f "$tmp"
    [[ -f "$soul" ]] && printf '\n' >> "$soul"
    hermes_soul_block >> "$soul"
  fi
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS (all Task4 checks).

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): merge metronix-config block into Hermes SOUL.md"
```

---

### Task 5: config.yaml merge via yq (+ yq detection)

**Files:**
- Modify: `install.sh`
- Test: `tests/installer/test_wire_hermes.sh`

**Interfaces:**
- Produces:
  - `have_yq() -> rc 0/1` — true if a usable `yq` is on PATH.
  - `merge_hermes_config <config_file>` — set `.mcp_servers.metronix` (url/headers/timeouts) via `yq -i`, preserving all other keys. Requires `have_yq`; caller guards.

- [ ] **Step 1: Write the failing test** (append before TOTAL)

```bash
echo "Task5: config.yaml yq merge (skips if yq absent)"
if bash -c "source '$INSTALL'; have_yq"; then
  d="$(mktemp -d)"; printf 'agent: hermes\nmcp_servers:\n  other:\n    url: http://other\n' > "$d/config.yaml"
  bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY1; H_AGENT=AID1; H_WS=MTRNIX; merge_hermes_config '$d/config.yaml'"
  chk "metronix url set" "$(yq -r '.mcp_servers.metronix.url' "$d/config.yaml")" "http://h:8000/mcp"
  chk "auth header set" "$(yq -r '.mcp_servers.metronix.headers.Authorization' "$d/config.yaml")" "Bearer KEY1"
  chk "agent header set" "$(yq -r '.mcp_servers.metronix.headers.X-Agent-Id' "$d/config.yaml")" "AID1"
  chk "other server preserved" "$(yq -r '.mcp_servers.other.url' "$d/config.yaml")" "http://other"
  chk "top-level preserved" "$(yq -r '.agent' "$d/config.yaml")" "hermes"
else
  echo "  SKIP: yq not installed — merge_hermes_config path not exercised"
fi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — `have_yq`/`merge_hermes_config` not defined (or SKIP line if yq absent, but `have_yq` is still undefined → it errors; that surfaces the missing function).

- [ ] **Step 3: Implement** (after `merge_soul_block`)

```bash
have_yq() { command -v yq >/dev/null 2>&1; }

# Set .mcp_servers.metronix in the Hermes config, preserving everything else.
# Requires yq (mikefarah v4). Caller must guard with have_yq.
merge_hermes_config() {
  local config="$1"
  [[ -f "$config" ]] || printf 'mcp_servers: {}\n' > "$config"
  H_URL="$H_URL" H_KEY="$H_KEY" H_AGENT="$H_AGENT" yq -i '
    .mcp_servers.metronix.url = strenv(H_URL) |
    .mcp_servers.metronix.headers.Authorization = "Bearer " + strenv(H_KEY) |
    .mcp_servers.metronix.headers."X-Agent-Id" = strenv(H_AGENT) |
    .mcp_servers.metronix.timeout = 180 |
    .mcp_servers.metronix.connect_timeout = 60
  ' "$config"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS (or the SKIP line, with `have_yq` defined). If yq is available locally, all 5 checks PASS. Install yq if you want to exercise this path: `brew install yq` / `apt-get install yq`.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): merge mcp_servers.metronix into Hermes config via yq"
```

---

### Task 6: Prompt-file fallback writer

**Files:**
- Modify: `install.sh`
- Test: `tests/installer/test_wire_hermes.sh`

**Interfaces:**
- Produces: `write_hermes_prompt_file <dest>` — write `hermes_prompt_doc` to `<dest>` and `ok` the path. Default dest `./metronix-hermes-setup.md`.

- [ ] **Step 1: Write the failing test** (append before TOTAL)

```bash
echo "Task6: prompt-file fallback"
d="$(mktemp -d)"
bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY1; H_AGENT=AID1; H_WS=MTRNIX; write_hermes_prompt_file '$d/setup.md'" >/dev/null
chk "file written" "$([[ -f "$d/setup.md" ]] && echo yes || echo no)" "yes"
chk "contains config block" "$(grep -c 'X-Agent-Id: AID1' "$d/setup.md")" "1"
chk "contains soul block" "$(grep -c -- '--- metronix-config ---' "$d/setup.md")" "1"
chk "no placeholders" "$(grep -c '{{' "$d/setup.md")" "0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — `write_hermes_prompt_file` not defined.

- [ ] **Step 3: Implement** (after `merge_hermes_config`)

```bash
# Write the paste-ready Hermes setup doc (the universal fallback).
write_hermes_prompt_file() {
  local dest="$1"
  hermes_prompt_doc > "$dest"
  ok "Wrote a ready-to-use Hermes setup guide to $dest"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): write paste-ready Hermes setup file (fallback)"
```

---

### Task 7: Orchestrator `wire_hermes()`

**Files:**
- Modify: `install.sh`
- Test: `tests/installer/test_wire_hermes.sh`

**Interfaces:**
- Consumes: `get_env`, `resolve_agent_id`, `merge_hermes_config`, `have_yq`, `merge_soul_block`, `write_hermes_prompt_file`, templates; globals `ASSUME_YES`, `WIRE_HERMES`, `METRONIX_URL`, `AGENT_ID`; `$HOME`.
- Produces: `wire_hermes()` — resolves values (`H_URL/H_KEY/H_AGENT/H_WS`), then:
  - Hermes present (`$HOME/.hermes/config.yaml`) AND (interactive-accept OR `-y --wire-hermes`) AND `have_yq` → backup both files, show diffs, apply `merge_hermes_config` + `merge_soul_block`, print restart note.
  - otherwise (declined / absent / no yq / bare `-y`) → `write_hermes_prompt_file ./metronix-hermes-setup.md`.
  - `H_KEY` blank (no MCP key in `.env`) → `warn` and write the prompt file (can't wire without a key).

- [ ] **Step 1: Write the failing test** (append before TOTAL)

```bash
echo "Task7: orchestrator (HOME stubbed)"
# absent Hermes -> prompt file, no ~/.hermes created
hd="$(mktemp -d)"; work="$(mktemp -d)"
( cd "$work" && HOME="$hd" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; METRONIX_MCP_API_KEY=K; DEFAULT_WORKSPACE_ID=MTRNIX; get_env(){ case \$1 in METRONIX_MCP_API_KEY) echo K;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }; wire_hermes" >/tmp/wh.txt 2>&1 )
chk "absent -> prompt file" "$([[ -f "$work/metronix-hermes-setup.md" ]] && echo yes || echo no)" "yes"
chk "absent -> no ~/.hermes" "$([[ -e "$hd/.hermes" ]] && echo yes || echo no)" "no"
# present + -y --wire-hermes + yq -> edits applied
if bash -c "source '$INSTALL'; have_yq"; then
  hd2="$(mktemp -d)"; mkdir -p "$hd2/.hermes"; printf 'agent: hermes\n' > "$hd2/.hermes/config.yaml"; printf 'Persona.\n' > "$hd2/.hermes/SOUL.md"
  ( HOME="$hd2" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; get_env(){ case \$1 in METRONIX_MCP_API_KEY) echo KEYZ;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }; wire_hermes" >/tmp/wh2.txt 2>&1 )
  chk "config wired" "$(yq -r '.mcp_servers.metronix.headers.Authorization' "$hd2/.hermes/config.yaml")" "Bearer KEYZ"
  chk "soul wired" "$(grep -c -- '--- metronix-config ---' "$hd2/.hermes/SOUL.md")" "1"
  chk "backup made" "$(ls "$hd2/.hermes/"config.yaml.bak-* 2>/dev/null | wc -l | tr -d ' ')" "1"
else
  echo "  SKIP: yq not installed — apply path not exercised"
fi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — `wire_hermes` not defined.

- [ ] **Step 3: Implement** (after `write_hermes_prompt_file`)

```bash
WEBUI_PORT=${WEBUI_PORT:-3080}   # (already defined near top; no-op safety)

# Back up a file to <file>.bak-<ts> before editing.
_backup_file() { [[ -f "$1" ]] && cp "$1" "$1.bak-$(date +%Y%m%d%H%M%S)"; }

wire_hermes() {
  local hermes_dir="$HOME/.hermes" config="$HOME/.hermes/config.yaml"
  local soul="$HOME/.hermes/SOUL.md"
  H_KEY="$(get_env METRONIX_MCP_API_KEY)"
  H_WS="$(get_env DEFAULT_WORKSPACE_ID)"; H_WS="${H_WS:-MTRNIX}"
  H_URL="${METRONIX_URL:-http://localhost:8000/mcp}"
  H_AGENT="$(resolve_agent_id "$config")"

  # Fallback in every can't/won't-auto-edit case: write the paste-ready guide.
  local prompt_dest="./metronix-hermes-setup.md"

  if [[ -z "$H_KEY" ]]; then
    warn "No METRONIX_MCP_API_KEY in .env — cannot wire an agent without it."
    write_hermes_prompt_file "$prompt_dest"; return 0
  fi
  if [[ ! -f "$config" && ! -d "$hermes_dir" ]]; then
    info "Hermes not found ($hermes_dir). Writing a setup guide to apply later."
    write_hermes_prompt_file "$prompt_dest"; return 0
  fi
  if ! have_yq; then
    warn "yq not found — cannot safely edit config.yaml. Writing a setup file instead."
    warn "  Install yq to enable auto-wiring: https://github.com/mikefarah/yq#install"
    write_hermes_prompt_file "$prompt_dest"; return 0
  fi

  # Render the proposed result into temp copies and show a diff BEFORE confirming
  # (spec §6: backup -> diff -> confirm). No live file is touched until apply.
  local tmp_cfg tmp_soul; tmp_cfg="$(mktemp)"; tmp_soul="$(mktemp)"
  if [[ -f "$config" ]]; then cp "$config" "$tmp_cfg"; else printf 'mcp_servers: {}\n' > "$tmp_cfg"; fi
  [[ -f "$soul" ]] && cp "$soul" "$tmp_soul"
  merge_hermes_config "$tmp_cfg"
  merge_soul_block "$tmp_soul"

  info "Found Hermes at $hermes_dir."
  info "Metronix MCP URL: $H_URL   (use host.docker.internal if Hermes runs in WSL2/Docker)"
  info "Proposed changes:"
  diff -u "$config" "$tmp_cfg" 2>/dev/null || true
  diff -u "${soul:-/dev/null}" "$tmp_soul" 2>/dev/null || true

  # Apply? -y --wire-hermes applies non-interactively; bare -y never edits ~/.hermes.
  local do_apply=false
  if [[ "$ASSUME_YES" == true ]]; then
    [[ "$WIRE_HERMES" == true ]] && do_apply=true
  else
    read -rp "Apply these changes to ~/.hermes? [Y/n]: " ans \
      || { err "Aborted (no input)."; exit 1; }
    [[ "$ans" =~ ^[Nn] ]] || do_apply=true
  fi

  if [[ "$do_apply" != true ]]; then
    rm -f "$tmp_cfg" "$tmp_soul"
    write_hermes_prompt_file "$prompt_dest"; return 0
  fi

  _backup_file "$config"
  _backup_file "$soul"
  mv "$tmp_cfg" "$config"
  mv "$tmp_soul" "$soul"
  ok "Wired Metronix into Hermes (agent_id=$H_AGENT, workspace=$H_WS)."
  info "Restart Hermes: /quit, then 'hermes'. Then optionally run Prompt 2/3 from"
  info "  docs/integrations/hermes.md to make Metronix your mandatory memory store."
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: PASS (absent-path checks always; apply-path checks when yq present, else SKIP). `bash -n install.sh` clean.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh
git commit -m "feat(installer): orchestrate Hermes wiring (detect, confirm, apply/fallback)"
```

---

### Task 8: Hook into `main()` + standalone path + docs note

**Files:**
- Modify: `install.sh` (`main()`)
- Test: `tests/installer/test_wire_hermes.sh`; verify existing `tests/installer/test_install.sh` still green
- Modify: `docs/integrations/hermes.md` (add a note that the installer can do Prompt 1)

**Interfaces:**
- Consumes: `wire_hermes`, `check_prereqs`, `detect_compose`, `cd "$REPO_ROOT"`; globals `WIRE_HERMES`.
- Produces: `main()` runs `wire_hermes` after `print_links` on a normal install; and when `--wire-hermes` is passed, a standalone path runs only `wire_hermes` (no build) and exits.

- [ ] **Step 1: Write the failing test** (append before TOTAL)

```bash
echo "Task8: standalone --wire-hermes does not build the stack"
hd="$(mktemp -d)"; work="$(mktemp -d)"; cp "$INSTALL" "$work/install.sh"
printf 'METRONIX_MCP_API_KEY=K\nDEFAULT_WORKSPACE_ID=MTRNIX\n' > "$work/.env"
( cd "$work" && HOME="$hd" bash -c "source ./install.sh; launch(){ echo BUILT; }; wait_health(){ :; }; print_links(){ :; }; check_prereqs(){ :; }; main --wire-hermes -y" >/tmp/wh3.txt 2>&1 )
chk "standalone did NOT build" "$(grep -q BUILT /tmp/wh3.txt && echo built || echo no)" "no"
chk "standalone wrote prompt or wired" "$([[ -f "$work/metronix-hermes-setup.md" || -f "$hd/.hermes/config.yaml" ]] && echo yes || echo no)" "yes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/installer/test_wire_hermes.sh`
Expected: FAIL — standalone path not implemented; `main` runs `launch` (prints BUILT).

- [ ] **Step 3: Implement** — update `main()` in `install.sh`

```bash
main() {
  parse_args "$@"
  cd "$REPO_ROOT"
  # Standalone agent-wiring: skip the stack build entirely.
  if [[ "$WIRE_HERMES" == true && "$ASSUME_YES" == true ]]; then
    [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found — run a full install first, or cd to the deployment dir."; exit 1; }
    wire_hermes
    exit 0
  fi
  check_prereqs
  configure
  launch
  wait_health
  print_links
  wire_hermes
}
```

Note: the interactive end-of-install `wire_hermes` offer runs for every successful install (memory and answers). The standalone shortcut requires `-y` together with `--wire-hermes` (a scripted, non-interactive re-wire); interactive `--wire-hermes` still goes through a normal run and is offered at the end.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/installer/test_wire_hermes.sh`
Then: `bash tests/installer/test_install.sh` (must still be 30 passed) and `bash tests/installer/test_failgen.sh` (13 passed).
Expected: all green. `bash -n install.sh` clean.

- [ ] **Step 5: Add the docs note** — append to `docs/integrations/hermes.md` after the intro

```markdown
> **Shortcut:** `./install.sh` (or `./install.sh --wire-hermes -y` to re-run just
> this) can perform **Prompt 1** for you — it detects `~/.hermes`, fills in the
> values from your deployment, and edits `config.yaml` + `SOUL.md` after showing a
> diff (backup kept). If `~/.hermes` is absent or `yq` isn't installed, it writes a
> ready-to-paste `metronix-hermes-setup.md` instead. Prompts 2 and 3 below remain
> manual.
```

- [ ] **Step 6: Commit**

```bash
git add install.sh tests/installer/test_wire_hermes.sh docs/integrations/hermes.md
git commit -m "feat(installer): run Hermes wiring after install + standalone --wire-hermes"
```

---

## Self-Review

**Spec coverage:**
- §3 boundary (Prompt 1 only) → Tasks 3/4/5 render & write config+SOUL; Prompt 2/3 never written. ✓
- §4 values/provenance/idempotency → Task 2 (id reuse/generate), Task 7 (key/workspace/url resolution). ✓
- §5 flow (found/decline/absent, `-y` rules) → Task 7 branches + Task 8 main wiring. ✓
- §6 mechanics/safety (yq, SOUL text, backup+diff+confirm) → Tasks 4/5/7. ✓
- §7 templates DRY + prompt file → Tasks 3/6. ✓
- §8 restart + Prompt 2/3 note → Task 7 output + Task 8 docs note. ✓
- §9 flags → Task 1. ✓
- §10 tests → each task ships tests in `tests/installer/test_wire_hermes.sh`; Task 8 reverifies existing suites. ✓
- §11 risks → yq fallback (Task 7), URL note (Task 7), template sync comment (Task 3), Hermes-only structure. ✓

**Diff display (§6):** Task 7 renders the proposed result into temp copies and prints `diff -u` for both files before any live change. Interactive: the `[Y/n]` follows the diff. `-y --wire-hermes` (scripted): the diff is printed for the record, then applied without prompting; originals are always backed up first. Matches the spec's "backup → diff → confirm" safety story.

**Placeholder scan:** no TBD/TODO; every code step shows real code. ✓

**Type/name consistency:** `H_URL/H_KEY/H_AGENT/H_WS` used consistently across Tasks 3–7; `merge_hermes_config`/`merge_soul_block`/`have_yq`/`resolve_agent_id`/`gen_agent_id`/`write_hermes_prompt_file`/`wire_hermes` names match between definition and callers. ✓
