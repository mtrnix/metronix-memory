#!/usr/bin/env bash
# Metronix Core installer — builds and starts the full stack from source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"
EXAMPLE_FILE=".env.example"
API_PORT=8000
WEBUI_PORT=3080
ADMIN_PORT="${ADMIN_FRONTEND_PORT:-${KB_FRONTEND_PORT:-3000}}"   # honor ADMIN_FRONTEND_PORT (legacy KB_FRONTEND_PORT still honored)

MODE=""              # "memory" | "answers" (how Metronix is used)
CHAT_URL=""          # OpenAI-compatible chat-model endpoint (answers mode)
CHAT_MODEL=""        # model name the endpoint serves (answers mode)
CHAT_API_KEY=""      # bearer token for the endpoint (optional; blank = no auth)
ENABLE_WEBUI=false
ENABLE_ADMIN=false     # install the Metronix Admin Console web UI (profile admin); --kb is a deprecated alias
ASSUME_YES=false
RECONFIGURE=false
FRESH_DOCKER_RESET=false
CONNECT_HERMES=false    # run the Hermes connection step (and, with -y, apply without prompt)
CONNECT_CLAUDE=false    # run the Claude Code connection step (and, with -y, apply without prompt)
CONNECT_CODEX=false    # run the Codex connection step (and, with -y, apply without prompt)
CONNECT_OPENCLAW=false  # run the OpenClaw connection step (and, with -y, apply without prompt)
AGENT_ID=""          # override the generated X-Agent-Id (Hermes/Claude Code/Codex/OpenClaw wiring)
METRONIX_URL=""      # override the MCP URL written into the agent config
COMPOSE=()

# State globals — set by diagnose_state(), read by resume_menu() / do_resume().
DIAG_ENV="no"; DIAG_ENV_ISSUES=""; DIAG_ANY_EXIST="no"
DIAG_ANY_UNHEALTHY="no"; DIAG_VOL_EXISTS="no"; DIAG_API_OK="no"
RESUME_ACTION=""

if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_RST=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_RST=""
fi
info() { printf '%s\n' "$*"; }
ok()   { printf '%s\xe2\x9c\x93%s %s\n' "$C_OK" "$C_RST" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_RST" "$*"; }
err()  { printf '%s\xe2\x9c\x97%s %s\n' "$C_ERR" "$C_RST" "$*" >&2; }

print_banner() {
  local cyan="" rst=""
  if [[ -t 1 ]]; then cyan=$'\033[36m'; rst=$'\033[0m'; fi
  printf '%s' "$cyan"
  cat <<'BANNER'

 __  __ ___ _____ ___  ___  _  _ ___ __  __  __  __ ___ __  __  ___  _____   __
|  \/  | __|_   _| _ \/ _ \| \| |_ _|\ \/ / |  \/  | __|  \/  |/ _ \| _ \ \ / /
| |\/| | _|  | | |   / (_) | .` || |  >  <  | |\/| | _|| |\/| | (_) |   /\ V /
|_|  |_|___| |_| |_|_\\___/|_|\_|___|/_/\_\ |_|  |_|___|_|  |_|\___/|_|_\ |_|

BANNER
  printf '%s\n' "$rst"
}

# Prompt for a required value, re-asking until the user enters something non-blank.
# Usage: prompt_required VAR_NAME "Prompt text: " [secret]
# Passing "secret" as the 3rd arg hides the input (for API keys).
prompt_required() {
  local __var="$1" __prompt="$2" __secret="${3:-}" __input
  while true; do
    if [[ "$__secret" == secret ]]; then
      read -rsp "$__prompt" __input || { echo; err "Aborted (no input)."; exit 1; }
      echo
    else
      read -rp "$__prompt" __input || { err "Aborted (no input)."; exit 1; }
    fi
    if [[ -n "$__input" ]]; then
      printf -v "$__var" '%s' "$__input"
      return 0
    fi
    warn "This value is required — please enter it (or press Ctrl-C to abort)."
  done
}

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Builds and starts Metronix Core from source via docker-compose.yml.

Vector embeddings always run locally on the bundled Ollama (model:
nomic-embed-text), set up automatically — no configuration needed. The options
below only concern answer generation (chat).

Options:
  --mode <memory|answers>  How Metronix is used:
                             memory  = a memory store for your own agent (e.g.
                                       Hermes); the agent generates its own
                                       answers. No chat model needed. (default)
                             answers = Metronix generates answers itself; point
                                       it at a chat-model endpoint below.
  --chat-url <url>         Chat-model endpoint, OpenAI-compatible (mode=answers):
                             http://host.docker.internal:11434/v1  (local Ollama)
                             https://api.deepseek.com/v1           (a cloud API)
  --chat-model <name>      Model the endpoint serves, e.g. deepseek-chat, llama3.1:8b
  --chat-api-key <key>     Bearer token for the endpoint (optional; blank = no auth)
  --openwebui              Enable the Open WebUI chat interface (:3080)
  --admin                  Install the Metronix Admin Console web UI (:3000, HTTPS)
  --kb                     Deprecated alias for --admin (renamed to Metronix Admin Console)
  --connect-hermes            Connect the Hermes agent to Metronix (edit ~/.hermes
                           config); with -y, apply without prompting. Also offered
                           interactively at the end of a normal install.
  --connect-claude         Connect Claude Code to Metronix (claude mcp add, or
                           edit ~/.claude.json if the CLI is unavailable); with
                           -y, apply without prompting (defaults to user scope).
                           Also offered interactively at the end of a normal
                           install.
  --connect-codex          Connect Codex to Metronix (edits ~/.codex/config.toml,
                           since `codex mcp add` cannot set custom headers);
                           with -y, apply without prompting (defaults to user
                           scope). Also offered interactively at the end of a
                           normal install.
  --connect-openclaw       Connect the OpenClaw agent to Metronix (edit ~/.openclaw
                           config); with -y, apply without prompting. Also offered
                           interactively at the end of a normal install.
  --agent-id <id>          Override the generated agent id (X-Agent-Id)
  --metronix-url <url>     MCP URL written into the agent config
                           (default http://localhost:8000/mcp)
  -y, --yes                Non-interactive: use defaults/flags, never prompt
  --reconfigure            Re-run configuration even if .env already exists
  --fresh-docker-reset     Delete Metronix Docker containers, images, volumes,
                           orphan containers, and build cache before reinstalling
  -h, --help               Show this help

If --chat-url is given, --mode defaults to "answers"; otherwise "memory".

Examples:
  ./install.sh                                    # memory store for an agent (default)
  ./install.sh --mode answers \
      --chat-url https://api.deepseek.com/v1 --chat-model deepseek-chat \
      --chat-api-key sk-...
  ./install.sh --chat-url http://host.docker.internal:11434/v1 \
      --chat-model llama3.1:8b -y                 # local Ollama, no token

Documentation:
  install.md               Full install: prerequisites, ports, troubleshooting
  connecting_to_agent.md   Connect an agent over MCP (auto or prompt-based)
  uninstall.md             Remove the stack, volumes, and agent wiring
  docs/README.md           Documentation index (API, integrations, guides)
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --mode)         [[ $# -ge 2 ]] || { err "--mode requires a value"; exit 2; }; MODE="$2"; shift 2 ;;
      --chat-url)     [[ $# -ge 2 ]] || { err "--chat-url requires a value"; exit 2; }; CHAT_URL="$2"; shift 2 ;;
      --chat-model)   [[ $# -ge 2 ]] || { err "--chat-model requires a value"; exit 2; }; CHAT_MODEL="$2"; shift 2 ;;
      --chat-api-key) [[ $# -ge 2 ]] || { err "--chat-api-key requires a value"; exit 2; }; CHAT_API_KEY="$2"; shift 2 ;;
      --connect-hermes)   CONNECT_HERMES=true; shift ;;
      --connect-claude)   CONNECT_CLAUDE=true; shift ;;
      --connect-codex)    CONNECT_CODEX=true; shift ;;
      --connect-openclaw) CONNECT_OPENCLAW=true; shift ;;
      --agent-id)      [[ $# -ge 2 ]] || { err "--agent-id requires a value"; exit 2; }; AGENT_ID="$2"; shift 2 ;;
      --metronix-url)  [[ $# -ge 2 ]] || { err "--metronix-url requires a value"; exit 2; }; METRONIX_URL="$2"; shift 2 ;;
      --openwebui)   ENABLE_WEBUI=true; shift ;;
      --admin)      ENABLE_ADMIN=true; shift ;;
      --kb)         warn "--kb is deprecated, use --admin (renamed to Metronix Admin Console)"; ENABLE_ADMIN=true; shift ;;
      -y|--yes)      ASSUME_YES=true; shift ;;
      --reconfigure) RECONFIGURE=true; shift ;;
      --fresh-docker-reset) FRESH_DOCKER_RESET=true; shift ;;
      -h|--help)     usage; exit 0 ;;
      *) err "Unknown option: $1"; usage >&2; exit 2 ;;
    esac
  done
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    return 1
  fi
}

check_prereqs() {
  command -v docker >/dev/null 2>&1 || {
    err "Docker not found. Install it: https://docs.docker.com/get-docker/"
    exit 1
  }
  detect_compose || {
    err "Docker Compose not found (need the v2 plugin 'docker compose' or 'docker-compose' v1)."
    info "  Linux: sudo apt-get install docker-compose-plugin"
    info "  macOS/Windows: ships with Docker Desktop / OrbStack"
    exit 1
  }
  if ! docker info >/dev/null 2>&1; then
    err "Docker daemon is not reachable."
    case "$(uname -s)" in
      Linux)  info "  Start it: sudo systemctl start docker" ;;
      Darwin) info "  Start Docker Desktop or OrbStack, or run: colima start" ;;
      *)      info "  Start Docker Desktop and re-run." ;;
    esac
    exit 1
  fi
  ok "Docker and Compose are ready (${COMPOSE[*]})"
}

# Read a single KEY's value from $ENV_FILE (empty if absent).
get_env() {
  [[ -f "$ENV_FILE" ]] || return 0
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

# Upsert KEY=VALUE in $ENV_FILE. Value is written literally (no shell/sed interpretation).
set_env() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    awk -v k="$key" -v v="$val" '
      $0 ~ "^" k "=" { print k "=" v; next }
      { print }
    ' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    rm -f "$tmp"
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

gen_fernet() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
  else
    head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'
  fi
}

# 32 lowercase hex chars — a stable, unique agent id for X-Agent-Id.
gen_agent_id() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]' | tr -d '-'
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# Best-effort read of the X-Agent-Id already registered for metronix in a Claude
# Code ~/.claude.json. Uses jq if available (host, else Docker); falls back to a
# plain grep/sed scan of the raw JSON so a missing jq never blocks id resolution.
claude_json_agent_id() {
  local config="$1"
  [[ -f "$config" ]] || return 0
  if jq_available; then
    jq_read "$config" '.mcpServers.metronix.headers["X-Agent-Id"] // ""' 2>/dev/null | tr -d '"'
  else
    grep -E '"X-Agent-Id"[[:space:]]*:' "$config" 2>/dev/null | head -1 \
      | sed -E 's/.*"X-Agent-Id"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/'
  fi
}

# Best-effort read of the X-Agent-Id already registered for metronix in a
# Codex ~/.codex/config.toml. Uses yq (-p toml) if available (host, else
# Docker); falls back to a plain grep/sed scan of the raw TOML so a missing
# yq never blocks id resolution.
codex_toml_agent_id() {
  local config="$1"
  [[ -f "$config" ]] || return 0
  if yq_available; then
    toml_read "$config" '.mcp_servers.metronix.http_headers["X-Agent-Id"] // ""' 2>/dev/null | tr -d '"'
  else
    grep -E '"X-Agent-Id"[[:space:]]*=' "$config" 2>/dev/null | head -1 \
      | sed -E 's/.*"X-Agent-Id"[[:space:]]*=[[:space:]]*"([^"]*)".*/\1/'
  fi
}

# Resolve the agent id, in priority order:
#   1. explicit --agent-id (operator override)
#   2. the X-Agent-Id already in the live Hermes config (source of truth for the
#      running agent — its memories are stored under this id)
#   3. the X-Agent-Id already in the live Claude Code config (~/.claude.json),
#      same reasoning as step 2 for that runtime
#   4. the X-Agent-Id already in the live Codex config (~/.codex/config.toml),
#      same reasoning again
#   5. METRONIX_AGENT_ID persisted in .env (installer's durable record; survives a
#      wiped/reset Hermes/Claude Code/Codex config so the agent keeps the same id,
#      and thus the same memories, across re-runs)
#   6. a freshly generated id
# The backend never reads an agent id from env — it comes from the X-Agent-Id
# request header — so METRONIX_AGENT_ID is purely the installer's own anchor.
# Hermes, Claude Code, and Codex share this one anchor by default (same human,
# same memory), unless --agent-id is used to separate them explicitly.
# connect_hermes() / connect_claude_code() / connect_codex() persist the resolved
# value back to .env.
resolve_agent_id() {
  local config="$1" claude_config="${2:-}" codex_config="${3:-}" existing persisted
  if [[ -n "$AGENT_ID" ]]; then printf '%s' "$AGENT_ID"; return 0; fi
  if [[ -f "$config" ]]; then
    existing="$(grep -E '^[[:space:]]*X-Agent-Id:' "$config" 2>/dev/null | head -1 | sed -E 's/.*X-Agent-Id:[[:space:]]*//' | tr -d '"' | tr -d '[:space:]')"
    if [[ -n "$existing" ]]; then printf '%s' "$existing"; return 0; fi
  fi
  if [[ -n "$claude_config" && -f "$claude_config" ]]; then
    existing="$(claude_json_agent_id "$claude_config")"
    if [[ -n "$existing" ]]; then printf '%s' "$existing"; return 0; fi
  fi
  if [[ -n "$codex_config" && -f "$codex_config" ]]; then
    existing="$(codex_toml_agent_id "$codex_config")"
    if [[ -n "$existing" ]]; then printf '%s' "$existing"; return 0; fi
  fi
  persisted="$(get_env METRONIX_AGENT_ID)"
  if [[ -n "$persisted" ]]; then printf '%s' "$persisted"; return 0; fi
  gen_agent_id
}

# --- Hermes wiring templates -------------------------------------------------
# These two blocks are used for the in-place auto-edit of config.yaml / SOUL.md.
# The paste-ready prompts (1/2/3) are NOT here — they live as canonical template
# files in docs/integrations/hermes/ and are filled by write_hermes_prompt_dir.
# KEEP the YAML/SOUL shape below in sync with docs/integrations/hermes/prompt-1-install.md.
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

# Fill a {{...}} prompt template with this deployment's values and write it to dest.
# Templates are the single source of truth (docs/integrations/hermes/prompt-*.md);
# the filled output contains the real MCP key, so it is per-deployment / gitignored.
fill_template() {
  local tmpl="$1" dest="$2" content
  content="$(cat "$tmpl")"
  content="${content//\{\{METRONIX_URL\}\}/$H_URL}"
  content="${content//\{\{METRONIX_MCP_API_KEY\}\}/$H_KEY}"
  content="${content//\{\{AGENT_UUID\}\}/$H_AGENT}"
  content="${content//\{\{DEFAULT_WORKSPACE_ID\}\}/$H_WS}"
  printf '%s\n' "$content" > "$dest"
}

# Write the ready-to-paste prompts (filled) for a runtime that ships its own
# docs/integrations/<runtime>/prompt-*.md template set — Hermes, Claude Code,
# and Codex all use this exact shape (install -> mandatory memory -> migrate;
# prompt 4 is an optional rollback of prompt 2). Returns 0 (with a warning) if
# no templates were found (e.g. install.sh run outside the repo) — never
# blocks the caller. $1=dir $2=runtime label for messages $3=template dir
# $4=doc path for the "full setup guide" pointer.
write_runtime_prompt_dir() {
  local dir="$1" label="$2" tdir="$3" doc="$4" found=0 pair src out
  mkdir -p "$dir"
  for pair in "prompt-1-install.md:1-install-mcp.md" \
              "prompt-2-memory.md:2-memory-source.md" \
              "prompt-3-migrate.md:3-migrate.md" \
              "prompt-4-rollback.md:4-rollback.md"; do
    src="$tdir/${pair%%:*}"; out="$dir/${pair#*:}"
    if [[ -f "$src" ]]; then fill_template "$src" "$out"; found=$((found + 1)); fi
  done
  if [[ "$found" -eq 0 ]]; then
    warn "Prompt templates not found under $tdir — run the installer from the repo checkout."
    return 0
  fi
  ok "Wrote $found ready-to-paste $label prompt(s) to $dir/ (apply 1 -> 2 -> 3 in order; 4 is an optional rollback of 2)."
  info "$label setup guide: $doc"
}

write_hermes_prompt_dir() {
  write_runtime_prompt_dir "$1" "Hermes" "$REPO_ROOT/docs/integrations/hermes" "docs/integrations/hermes-agent.md"
}

write_claude_prompt_dir() {
  write_runtime_prompt_dir "$1" "Claude Code" "$REPO_ROOT/docs/integrations/claude-code" "docs/integrations/claude-code.md"
}

write_codex_prompt_dir() {
  write_runtime_prompt_dir "$1" "Codex" "$REPO_ROOT/docs/integrations/codex" "docs/integrations/codex.md"
}

# Write the ready-to-paste, runtime-agnostic setup prompts (filled with this
# deployment's values) for any MCP client other than Hermes. Source of truth is
# prompts.md at the repo root; the filled copy contains the real MCP key, so it
# is per-deployment / gitignored.
write_generic_prompt_dir() {
  local dir="$1" src="$REPO_ROOT/prompts.md" out
  if [[ ! -f "$src" ]]; then
    warn "prompts.md not found at $src — run the installer from the repo checkout."
    info "The four values above plus connecting_to_agent.md are enough to connect by hand."
    return 0
  fi
  if [[ -z "$H_KEY" ]]; then
    warn "No METRONIX_MCP_API_KEY in .env — the prompts will have an empty Bearer token."
    warn "Set it in .env (e.g. 'openssl rand -hex 32'), then re-run or fill it into the prompts by hand."
  fi
  mkdir -p "$dir"
  out="$dir/prompts.md"
  fill_template "$src" "$out"
  ok "Wrote ready-to-paste agent setup prompts to $out (apply Prompt 1, restart the runtime, then 2 and 3)."
  info "Where to register the MCP server per runtime: see docs/integrations/ (cursor.md, claude-desktop.md, claude-code.md, codex.md, opencode.md, ...)."
}

# Ensure exactly one metronix-config block in the SOUL file. Replaces the body
# between the markers in place if present; otherwise appends. Content outside
# the markers is untouched.
merge_soul_block() {
  local soul="$1" tmp; tmp="$(mktemp)"
  # Take the replace path only when BOTH markers are present. With an orphan
  # opening marker (no end marker) the awk below would set skip=1 and never
  # reset, silently dropping everything after it — so fall through to append.
  if [[ -f "$soul" ]] && grep -qF -- '--- metronix-config ---' "$soul" \
       && grep -qF -- '--- end metronix-config ---' "$soul"; then
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

# yq is a small YAML processor ("jq for YAML"). We use it ONLY to READ/validate
# the Hermes config (never `yq -i`, which would re-serialize and reformat the
# whole file). The actual change is a minimal text edit (see merge_hermes_config),
# so the user's formatting, comments, and key order are left untouched. We never
# require a host install: if `yq` is not on PATH we run the tiny mikefarah/yq
# image via Docker (already a hard dependency of this installer).
yq_available()    { command -v yq >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; }
yq_needs_docker() { ! command -v yq >/dev/null 2>&1; }

# yq_read FILE EXPR — evaluate a read-only yq expression and print the result.
# Host yq if present, else mikefarah/yq in Docker with the file's dir mounted
# READ-ONLY (:ro) — the file is never modified by yq.
yq_read() {
  local file="$1" expr="$2"
  if command -v yq >/dev/null 2>&1; then
    yq "$expr" "$file"
  else
    local dir base; dir="$(cd "$(dirname "$file")" && pwd)"; base="$(basename "$file")"
    docker run --rm --user "$(id -u):$(id -g)" -v "$dir:/work:ro" -w /work mikefarah/yq "$expr" "$base"
  fi
}

# openclaw detection: the CLI is required for the safe (schema-owned-by-the-tool)
# edit path; a directory with no binary on PATH still counts as "found" so the
# guide fallback still fires (rather than silently doing nothing), matching how
# connect_hermes degrades when yq/Docker aren't available.
openclaw_cli_available() { command -v openclaw >/dev/null 2>&1; }
openclaw_found()         { openclaw_cli_available || [[ -d "$HOME/.openclaw" ]]; }

# Minimal JSON string escaping for values we interpolate into a JSON literal
# passed to `openclaw mcp set` (H_KEY/H_URL/H_AGENT are installer-controlled but
# not guaranteed quote-free — e.g. a hand-edited METRONIX_MCP_API_KEY).
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

# Build the `openclaw mcp set metronix <json>` payload. Callers set H_URL / H_KEY
# / H_AGENT first (resolve_agent_connection already does this for Hermes; reused
# as-is here). Schema (url/transport/headers/timeout/connectTimeout) sourced from
# https://docs.openclaw.ai/cli/mcp — re-verify there if OpenClaw's CLI changes.
# The literal secret is written here by design — see this plan's Global
# Constraints for why ${VAR}-style env indirection was rejected for OpenClaw.
openclaw_mcp_json() {
  local url key agent
  url="$(json_escape "$H_URL")"
  key="$(json_escape "$H_KEY")"
  agent="$(json_escape "$H_AGENT")"
  printf '{"url":"%s","transport":"streamable-http","headers":{"Authorization":"Bearer %s","X-Agent-Id":"%s"},"timeout":180,"connectTimeout":60}' \
    "$url" "$key" "$agent"
}

# toml_read FILE EXPR — same contract as yq_read, but for TOML input (used
# ONLY for the Codex config.toml, via yq's `-p toml` decoder). yq can read
# TOML but cannot write/round-trip it, which is exactly why Codex's config is
# edited as a minimal text patch (see merge_codex_config) and toml_read is
# only ever used to validate the result, mirroring yq_read's role for Hermes.
# Reuses yq_available/yq_needs_docker — no new tool dependency.
toml_read() {
  local file="$1" expr="$2"
  if command -v yq >/dev/null 2>&1; then
    yq -p toml "$expr" "$file"
  else
    local dir base; dir="$(cd "$(dirname "$file")" && pwd)"; base="$(basename "$file")"
    docker run --rm --user "$(id -u):$(id -g)" -v "$dir:/work:ro" -w /work mikefarah/yq -p toml "$expr" "$base"
  fi
}

# jq is the JSON equivalent of yq above, used ONLY for the Claude Code fallback
# path (editing ~/.claude.json when the `claude` CLI is unavailable). Unlike the
# Hermes YAML edit, JSON has no safe "insert a couple of lines" trick — the file
# must be parsed and re-serialized — so jq (not a text patch) does the edit
# itself in merge_claude_json below; it is still validated before being kept.
# Same no-host-install guarantee as yq: fall back to a jq Docker image.
jq_available()    { command -v jq >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; }
jq_needs_docker()  { ! command -v jq >/dev/null 2>&1; }

# jq_read FILE EXPR — evaluate a read-only jq expression and print the result.
jq_read() {
  local file="$1" expr="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r "$expr" "$file"
  else
    local dir base; dir="$(cd "$(dirname "$file")" && pwd)"; base="$(basename "$file")"
    docker run --rm --user "$(id -u):$(id -g)" -v "$dir:/work:ro" -w /work ghcr.io/jqlang/jq -r "$expr" "$base"
  fi
}

# jq_write FILE EXPR [jq-args...] — evaluate a jq expression against FILE
# (with any extra --arg/--argjson flags forwarded to jq) and print the
# resulting JSON to stdout (caller redirects to a temp file). Never edits FILE
# in place — same read-only-mount pattern as jq_read for the Docker path.
jq_write() {
  local file="$1" expr="$2"; shift 2
  if command -v jq >/dev/null 2>&1; then
    jq "$@" "$expr" "$file"
  else
    local dir base; dir="$(cd "$(dirname "$file")" && pwd)"; base="$(basename "$file")"
    docker run --rm --user "$(id -u):$(id -g)" -v "$dir:/work:ro" -w /work ghcr.io/jqlang/jq "$@" "$expr" "$base"
  fi
}

# Classify a config: "has_metronix" | "has_mcp" (mcp_servers but no metronix) | "none".
# Uses mikefarah-yq-compatible boolean reads (no jq-style if/then/else).
hermes_mcp_state() {
  local file="$1"
  if [[ "$(yq_read "$file" '.mcp_servers.metronix != null' 2>/dev/null)" == "true" ]]; then
    echo has_metronix
  elif [[ "$(yq_read "$file" '.mcp_servers != null' 2>/dev/null)" == "true" ]]; then
    echo has_mcp
  else
    echo none
  fi
}

# Add the metronix MCP server to a Hermes config with a MINIMAL text edit (no
# reformatting of the rest of the file). Three cases, decided by hermes_mcp_state:
#   - has_metronix : already present -> return 1 (no change; caller skips)
#   - has_mcp      : insert the metronix entry right after the 'mcp_servers:' line
#   - none         : append a fresh 'mcp_servers:' section at the end
# The caller must validate the result (yq_read) — an unusual layout (e.g. inline
# 'mcp_servers: {}') can leave nothing inserted, which validation catches.
# Caller must guard with yq_available (hermes_mcp_state needs yq).
merge_hermes_config() {
  local config="$1" state ln tmp
  state="$(hermes_mcp_state "$config")"
  case "$state" in
    has_metronix)
      return 1
      ;;
    has_mcp)
      ln="$(grep -nE '^mcp_servers:[[:space:]]*$' "$config" | head -1 | cut -d: -f1)"
      [[ -n "$ln" ]] || return 0   # no plain 'mcp_servers:' line to anchor to; validation will catch it
      tmp="$(mktemp "$(dirname "$config")/.metronix-ins.XXXXXX")"
      { head -n "$ln" "$config"; hermes_config_block; tail -n +"$((ln + 1))" "$config"; } > "$tmp"
      mv "$tmp" "$config"
      ;;
    *)
      [[ -s "$config" ]] && printf '\n' >> "$config"
      printf 'mcp_servers:\n' >> "$config"
      hermes_config_block >> "$config"
      ;;
  esac
}

# --- Codex config.toml templates ---------------------------------------------
# Codex's own CLI (`codex mcp add`) cannot set custom HTTP headers — only
# --url and --bearer-token-env-var (plus OAuth) — so it can't set the
# X-Agent-Id Metronix requires. Registration is therefore a minimal TEXT edit
# of config.toml, exactly like Hermes's config.yaml, rather than a CLI call.
# Callers set H_URL / H_KEY / H_AGENT before calling (same shared globals used
# by the Hermes/Claude Code/generic paths).
codex_config_block() {
  cat <<EOF

[mcp_servers.metronix]
url = "$H_URL"
http_headers = { "Authorization" = "Bearer $H_KEY", "X-Agent-Id" = "$H_AGENT" }
startup_timeout_sec = 10.0
tool_timeout_sec = 60.0
EOF
}

# Classify a config.toml: "has_metronix" | "needs_agent_id" | "none".
# "needs_agent_id" catches a [mcp_servers.metronix] table that exists but has
# no (or an empty) X-Agent-Id header — e.g. added by `codex mcp add` (which
# can't set custom headers) or an older/manual config. That entry would
# otherwise be silently treated as "already configured" even though it can't
# reach the agent's memories, and `codex mcp list` won't catch it either
# since it only checks presence by name.
codex_toml_state() {
  local file="$1"
  if [[ "$(toml_read "$file" '.mcp_servers.metronix != null' 2>/dev/null)" == "true" ]]; then
    if [[ -z "$(codex_toml_agent_id "$file")" ]]; then
      echo needs_agent_id
    else
      echo has_metronix
    fi
  else
    echo none
  fi
}

# Add the metronix MCP server to a Codex config with a MINIMAL text edit (no
# reformatting of the rest of the file). Decided by codex_toml_state:
#   - has_metronix   : already present with an X-Agent-Id -> return 1 (no
#                       change; caller skips)
#   - needs_agent_id : present but missing/empty X-Agent-Id -> return 2 (no
#                       change; caller must warn — repairing an existing
#                       table in place isn't a minimal text edit)
#   - none           : append a fresh [mcp_servers.metronix] table at the end
# The caller must validate the result (toml_read) — an unusual layout (e.g. an
# inline `mcp_servers = { ... }` table) can leave nothing inserted, which
# validation catches. Caller must guard with yq_available (codex_toml_state
# needs yq -p toml).
merge_codex_config() {
  local config="$1" state
  state="$(codex_toml_state "$config")"
  case "$state" in
    has_metronix)
      return 1
      ;;
    needs_agent_id)
      return 2
      ;;
    *)
      codex_config_block >> "$config"
      ;;
  esac
}

# Back up a file to <file>.bak-<ts> before editing. Always succeeds (exit 0)
# even when there's nothing to back up — callers invoke this as a bare
# statement under `set -e`, and "[[ -f ]] && cp" would make the function
# return the test's failure status when the file doesn't exist yet, which
# would abort the whole script. The explicit if/fi avoids that. This
# missing-file-returns-0 contract is locked in by tests/installer/test_backup_file.sh.
_backup_file() {
  if [[ -f "$1" ]]; then
    cp "$1" "$1.bak-$(date +%Y%m%d%H%M%S)"
  fi
}

# Resolve the four agent-connection values once and anchor the agent id in .env.
# Idempotent (guarded): connect_agent resolves first, and the default Hermes
# choice then calls connect_hermes — without the guard that would recompute the
# same values and rewrite METRONIX_AGENT_ID. Also covers the standalone
# connect_hermes path (--connect-hermes -y), which never goes through connect_agent.
resolve_agent_connection() {
  [[ -n "${AGENT_CONN_RESOLVED:-}" ]] && return 0
  local config="$HOME/.hermes/config.yaml" claude_config="$HOME/.claude.json" \
        codex_config="$HOME/.codex/config.toml"
  H_KEY="$(get_env METRONIX_MCP_API_KEY)"
  H_WS="$(get_env DEFAULT_WORKSPACE_ID)"; H_WS="${H_WS:-MTRNIX}"
  H_URL="${METRONIX_URL:-http://localhost:8000/mcp}"
  H_AGENT="$(resolve_agent_id "$config" "$claude_config" "$codex_config")"
  # Anchor the agent id in .env so re-runs reuse it even if the Hermes/Claude
  # Code/Codex config is later reset — keeping the agent's memories under one
  # stable id.
  [[ -f "$ENV_FILE" ]] && set_env METRONIX_AGENT_ID "$H_AGENT"
  AGENT_CONN_RESOLVED=1
}

connect_hermes() {
  local hermes_dir="$HOME/.hermes" config="$HOME/.hermes/config.yaml"
  local soul="$HOME/.hermes/SOUL.md"
  # If connect_agent already resolved and printed the values, don't repeat them.
  local printed="${AGENT_CONN_RESOLVED:-}"
  resolve_agent_connection

  # Fallback in every can't/won't-auto-edit case: write the paste-ready guide.
  local prompt_dir="./metronix-hermes-setup"

  if [[ -z "$H_KEY" ]]; then
    warn "No METRONIX_MCP_API_KEY in .env — cannot wire an agent without it."
    write_hermes_prompt_dir "$prompt_dir"; return 0
  fi
  if [[ ! -f "$config" && ! -d "$hermes_dir" ]]; then
    info "Hermes not found ($hermes_dir). Writing a setup guide to apply later."
    write_hermes_prompt_dir "$prompt_dir"; return 0
  fi

  info "Found Hermes at $hermes_dir."
  [[ -z "$printed" ]] && info "Metronix MCP URL: $H_URL   (use host.docker.internal if Hermes runs in WSL2/Docker)"

  # How does the user want to connect Hermes?
  local method
  if [[ "$ASSUME_YES" == true ]]; then
    if [[ "$CONNECT_HERMES" == true ]]; then method=edit; else method=guide; fi
  else
    info "Connect Hermes to Metronix:"
    info "  1) Edit ~/.hermes for me — add only the MCP block (minimal change)   [default]"
    info "  2) Just write a ready-to-paste guide — I'll apply it myself"
    read -rp "Choose 1 or 2 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
    case "${ans:-1}" in
      1|"") method=edit ;;
      2)    method=guide ;;
      *)    err "Invalid choice: $ans"; exit 1 ;;
    esac
  fi

  if [[ "$method" == guide ]]; then
    write_hermes_prompt_dir "$prompt_dir"
    info "Paste each into Hermes in order (1 install, 2 memory policy, 3 migrate)."
    return 0
  fi

  # method == edit. Editing config.yaml safely needs yq (read-only) to detect the
  # current shape and validate the result; if it isn't available, fall back.
  if ! yq_available; then
    warn "Editing config.yaml safely needs yq or Docker, and neither is available —"
    warn "writing a ready-to-paste guide instead so your file isn't touched."
    write_hermes_prompt_dir "$prompt_dir"; return 0
  fi
  if yq_needs_docker; then
    info "Reading/validating config.yaml with yq via Docker (image mikefarah/yq, pulled once)."
  fi

  # Build the change on temp copies (inside ~/.hermes: Docker-visible + atomic mv).
  # config.yaml is edited as plain text (minimal diff); yq only reads/validates it.
  local tmp_cfg tmp_soul
  tmp_cfg="$(mktemp "$hermes_dir/.metronix-cfg.XXXXXX")"
  tmp_soul="$(mktemp "$hermes_dir/.metronix-soul.XXXXXX")"
  [[ -f "$config" ]] && cp "$config" "$tmp_cfg"
  [[ -f "$soul" ]] && cp "$soul" "$tmp_soul"

  local cfg_changed=true
  if merge_hermes_config "$tmp_cfg"; then
    # We added the block — validate it parses and reads back our URL. If not, the
    # config has an unusual layout we won't risk editing: fall back to the guide.
    if [[ "$(yq_read "$tmp_cfg" '.mcp_servers.metronix.url' 2>/dev/null)" != "$H_URL" ]]; then
      warn "Could not safely edit config.yaml (its structure is unusual) —"
      warn "writing a ready-to-paste guide instead so your file isn't touched."
      rm -f "$tmp_cfg" "$tmp_soul"
      write_hermes_prompt_dir "$prompt_dir"; return 0
    fi
  else
    cfg_changed=false
    info "Metronix is already present in config.yaml — leaving it unchanged."
  fi
  merge_soul_block "$tmp_soul"

  info "Proposed changes:"
  [[ "$cfg_changed" == true ]] && { diff -u "$config" "$tmp_cfg" 2>/dev/null || true; }
  [[ -f "$soul" ]] && { diff -u "$soul" "$tmp_soul" 2>/dev/null || true; }

  _backup_file "$config"
  _backup_file "$soul"
  if [[ "$cfg_changed" == true ]]; then mv "$tmp_cfg" "$config"; else rm -f "$tmp_cfg"; fi
  mv "$tmp_soul" "$soul"
  ok "Wired Metronix into Hermes (agent_id=$H_AGENT, workspace=$H_WS) — prompt 1 applied."
  # Always leave all three filled prompts on disk so 2 (mandatory memory) and 3
  # (migrate) are ready to paste; 1 is included for reference / re-runs.
  write_hermes_prompt_dir "$prompt_dir" || true
  info "Restart Hermes (/quit, then 'hermes'). Then paste prompts 2 and 3 from"
  info "  $prompt_dir/ to make Metronix the mandatory memory store and migrate existing memory."
}

# --- Claude Code wiring -------------------------------------------------------
# Claude Code, unlike Hermes, ships a first-party CLI (`claude mcp add`) that
# manages ~/.claude.json for us — no hand-rolled minimal text edit needed in the
# common case. We only fall back to editing ~/.claude.json ourselves (via jq)
# when the CLI is missing or the add fails.

# "Present" if the CLI is on PATH, or its config file/dir exists (a CLI-less
# check covers an install whose binary isn't on this shell's PATH).
claude_code_present() {
  command -v claude >/dev/null 2>&1 && return 0
  [[ -f "$HOME/.claude.json" || -d "$HOME/.claude" ]]
}

claude_cli_available() { command -v claude >/dev/null 2>&1; }

# True (0) if a `metronix` MCP server is already registered, in either the CLI
# view or (when the CLI is unavailable) the raw ~/.claude.json.
claude_mcp_exists() {
  if claude_cli_available; then
    claude mcp get metronix >/dev/null 2>&1
  elif [[ -f "$HOME/.claude.json" ]] && jq_available; then
    [[ "$(jq_read "$HOME/.claude.json" '.mcpServers.metronix != null')" == "true" ]]
  else
    return 1
  fi
}

# Register metronix via the official CLI. $1 = scope (user|project|local).
register_via_cli() {
  local scope="$1"
  claude mcp add --transport http --scope "$scope" metronix "$H_URL" \
    --header "Authorization: Bearer $H_KEY" \
    --header "X-Agent-Id: $H_AGENT"
}

# Fallback used only when the CLI is absent or register_via_cli failed: add the
# metronix entry to ~/.claude.json with jq (re-serializes the file; formatting
# is not preserved, but the data is). Validates the result before committing,
# and backs up the original first. Returns 1 if jq is unavailable or the
# result doesn't validate — caller falls back to the prompt dir.
register_via_json_edit() {
  local config="$HOME/.claude.json" tmp
  if ! jq_available; then
    warn "Editing ~/.claude.json safely needs jq or Docker, and neither is available."
    return 1
  fi
  if jq_needs_docker; then
    info "Editing ~/.claude.json with jq via Docker (image ghcr.io/jqlang/jq, pulled once)."
  fi
  [[ -f "$config" ]] || printf '{}' > "$config"
  tmp="$(mktemp "$HOME/.metronix-claude.XXXXXX")"
  # $u/$k/$a below are jq variables (bound via --arg), not shell variables —
  # the filter is deliberately single-quoted so the shell leaves them alone.
  # shellcheck disable=SC2016
  if ! jq_write "$config" \
      '(.mcpServers = (.mcpServers // {})) | (.mcpServers.metronix = {type:"http", url:$u, headers:{"Authorization":("Bearer " + $k), "X-Agent-Id":$a}})' \
      --arg u "$H_URL" --arg k "$H_KEY" --arg a "$H_AGENT" > "$tmp" 2>/dev/null; then
    rm -f "$tmp"; return 1
  fi
  if [[ "$(jq_read "$tmp" '.mcpServers.metronix.url')" != "$H_URL" ]]; then
    rm -f "$tmp"; return 1
  fi
  _backup_file "$config"
  mv "$tmp" "$config"
  return 0
}

connect_claude_code() {
  local printed="${AGENT_CONN_RESOLVED:-}"
  resolve_agent_connection

  local prompt_dir="./metronix-claude-code-setup"

  if [[ -z "$H_KEY" ]]; then
    warn "No METRONIX_MCP_API_KEY in .env — cannot wire an agent without it."
    write_claude_prompt_dir "$prompt_dir"; return 0
  fi
  if ! claude_code_present; then
    info "Claude Code not found. Writing a setup guide to apply later."
    write_claude_prompt_dir "$prompt_dir"; return 0
  fi

  info "Found Claude Code."
  [[ -z "$printed" ]] && info "Metronix MCP URL: $H_URL   (use host.docker.internal if Claude Code runs in WSL2/Docker)"

  if claude_mcp_exists; then
    info "Metronix is already registered in Claude Code — leaving it unchanged."
    write_claude_prompt_dir "$prompt_dir" || true
    return 0
  fi

  # Which scope? Interactive: ask (default user). Non-interactive: always user,
  # no override flag — --connect-claude just connects the common case unattended.
  local scope=user
  if [[ "$ASSUME_YES" == false ]]; then
    info "Register Metronix at which Claude Code scope?"
    info "  1) User    - available in every project on this machine   [default]"
    info "  2) Project - written to ./.mcp.json, shared via git (put the API key in version control)"
    info "  3) Local   - private to you, this project only"
    read -rp "Choose 1, 2 or 3 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
    case "${ans:-1}" in
      1|"") scope=user ;;
      2)    scope=project; warn "Project scope writes the Bearer token into ./.mcp.json, which is typically committed to git." ;;
      3)    scope=local ;;
      *)    err "Invalid choice: $ans"; exit 1 ;;
    esac
  fi

  local registered=false
  if claude_cli_available; then
    if register_via_cli "$scope"; then
      registered=true
    else
      warn "claude mcp add failed — falling back to editing ~/.claude.json directly."
    fi
  fi
  if [[ "$registered" == false ]]; then
    if register_via_json_edit; then
      registered=true
    else
      warn "Could not safely edit ~/.claude.json — writing a ready-to-paste guide instead so your file isn't touched."
      write_claude_prompt_dir "$prompt_dir"; return 0
    fi
  fi

  ok "Wired Metronix into Claude Code (agent_id=$H_AGENT, workspace=$H_WS, scope=$scope) — prompt 1 applied."

  if claude_cli_available; then
    info "Verifying with 'claude mcp list':"
    if claude mcp list 2>/dev/null | grep -qi metronix; then
      ok "metronix appears in 'claude mcp list'."
    else
      warn "metronix did not show up in 'claude mcp list' — restart Claude Code and check again."
    fi
  fi

  # Always leave all filled prompts on disk so 2 (mandatory memory) and 3
  # (migrate) are ready to paste; 1 is included for reference / re-runs.
  write_claude_prompt_dir "$prompt_dir" || true
  info "Restart Claude Code. Then paste prompts 2 and 3 from"
  info "  $prompt_dir/ to make Metronix the mandatory memory store and migrate existing memory."
}

# --- Codex connection ---------------------------------------------------------
# codex mcp add cannot set custom headers, so — unlike Claude Code — there is
# no CLI-first path here at all: registration goes straight to a validated
# text edit of config.toml, same shape as connect_hermes's config.yaml edit.

# "Present" if the CLI is on PATH, or its config file/dir exists (a CLI-less
# check covers an install whose binary isn't on this shell's PATH).
codex_present() {
  command -v codex >/dev/null 2>&1 && return 0
  [[ -f "$HOME/.codex/config.toml" || -d "$HOME/.codex" ]]
}

codex_cli_available() { command -v codex >/dev/null 2>&1; }

connect_codex() {
  local codex_dir="$HOME/.codex" config="$HOME/.codex/config.toml"
  local printed="${AGENT_CONN_RESOLVED:-}"
  resolve_agent_connection

  local prompt_dir="./metronix-codex-setup"

  if [[ -z "$H_KEY" ]]; then
    warn "No METRONIX_MCP_API_KEY in .env — cannot wire an agent without it."
    write_codex_prompt_dir "$prompt_dir"; return 0
  fi
  if ! codex_present; then
    info "Codex not found ($codex_dir). Writing a setup guide to apply later."
    write_codex_prompt_dir "$prompt_dir"; return 0
  fi

  info "Found Codex."
  [[ -z "$printed" ]] && info "Metronix MCP URL: $H_URL   (use host.docker.internal if Codex runs in WSL2/Docker)"

  # Which scope? Interactive: ask (default user). Non-interactive: always user,
  # no override flag — --connect-codex just connects the common case unattended.
  local scope=user target="$config"
  if [[ "$ASSUME_YES" == false ]]; then
    info "Register Metronix at which Codex scope?"
    info "  1) User    - ~/.codex/config.toml, every project on this machine   [default]"
    info "  2) Project - ./.codex/config.toml, this project only (must also be marked \"trusted\" in Codex)"
    read -rp "Choose 1 or 2 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
    case "${ans:-1}" in
      1|"") scope=user; target="$config" ;;
      2)    scope=project; target="./.codex/config.toml"
            warn "Project scope writes the Bearer token into ./.codex/config.toml, which is typically committed to git."
            warn "Codex also requires this project be marked \"trusted\" before it will load that file." ;;
      *)    err "Invalid choice: $ans"; exit 1 ;;
    esac
  fi

  # Editing config.toml safely needs yq (read-only, -p toml) to detect the
  # current shape and validate the result; if it isn't available, fall back.
  if ! yq_available; then
    warn "Editing config.toml safely needs yq or Docker, and neither is available —"
    warn "writing a ready-to-paste guide instead so your file isn't touched."
    write_codex_prompt_dir "$prompt_dir"; return 0
  fi
  if yq_needs_docker; then
    info "Reading/validating config.toml with yq via Docker (image mikefarah/yq, pulled once)."
  fi

  # Build the change on a temp copy (same dir as target: Docker-visible +
  # atomic mv), same sequence connect_hermes uses for config.yaml.
  mkdir -p "$(dirname "$target")"
  local tmp_cfg
  tmp_cfg="$(mktemp "$(dirname "$target")/.metronix-cfg.XXXXXX")"
  [[ -f "$target" ]] && cp "$target" "$tmp_cfg"

  local cfg_changed=true merge_status=0
  merge_codex_config "$tmp_cfg" || merge_status=$?
  if [[ "$merge_status" -eq 0 ]]; then
    if [[ "$(toml_read "$tmp_cfg" '.mcp_servers.metronix.url' 2>/dev/null)" != "$H_URL" ]]; then
      warn "Could not safely edit config.toml (its structure is unusual) —"
      warn "writing a ready-to-paste guide instead so your file isn't touched."
      rm -f "$tmp_cfg"
      write_codex_prompt_dir "$prompt_dir"; return 0
    fi
  elif [[ "$merge_status" -eq 2 ]]; then
    cfg_changed=false
    warn "Metronix is present in config.toml but missing its X-Agent-Id header —"
    warn "the connection won't reach your agent's memories. Not editing an existing"
    warn "table automatically; remove the [mcp_servers.metronix] block and re-run,"
    warn "or add the header manually:"
    warn "  http_headers = { \"Authorization\" = \"Bearer <key>\", \"X-Agent-Id\" = \"$H_AGENT\" }"
  else
    cfg_changed=false
    info "Metronix is already present in config.toml — leaving it unchanged."
  fi

  if [[ "$cfg_changed" == true ]]; then
    info "Proposed changes:"
    diff -u "$target" "$tmp_cfg" 2>/dev/null || true
    _backup_file "$target"
    mv "$tmp_cfg" "$target"
    ok "Wired Metronix into Codex (agent_id=$H_AGENT, workspace=$H_WS, scope=$scope) — prompt 1 applied."
  else
    rm -f "$tmp_cfg"
  fi

  if codex_cli_available; then
    info "Verifying with 'codex mcp list':"
    if codex mcp list 2>/dev/null | grep -qi metronix; then
      ok "metronix appears in 'codex mcp list'."
    else
      warn "metronix did not show up in 'codex mcp list' — restart Codex and check again."
    fi
  fi

  # Always leave all filled prompts on disk so 2 (mandatory memory) and 3
  # (migrate) are ready to paste; 1 is included for reference / re-runs.
  write_codex_prompt_dir "$prompt_dir" || true
  info "Restart Codex. Then paste prompts 2 and 3 from"
  info "  $prompt_dir/ to make Metronix the mandatory memory store and migrate existing memory."
}

# --- OpenClaw connection ------------------------------------------------------
# OpenClaw ships its own CLI (`openclaw mcp set`) that owns its JSON5 config, so
# — like Claude Code — registration goes through the CLI, never a hand-edit of
# openclaw.json. Falls back to the generic prompt guide on any detection gap.

# Classify the current `metronix` entry in OpenClaw's config via the CLI itself
# (never by hand-parsing openclaw.json, which is JSON5 — comments/trailing commas
# a plain parser would corrupt). "none" covers both "not configured" and "CLI
# errored" — either way the caller's next step is to (re)run `mcp set`.
# "has_current" requires URL, API key, AND agent id to all match — a stack
# reinstall rotates METRONIX_MCP_API_KEY while the URL stays the same, and
# treating that as "already configured" would leave a stale key in
# openclaw.json (the agent then gets 401 on every metronix call).
# The key comparison relies on `mcp show` printing the entry unredacted —
# verified live against OpenClaw 2026.6.11. If a future version redacts
# secrets in `show` output, the key grep stops matching and every run
# re-invokes `mcp set` with identical values: idempotency degrades, but the
# config always ends up correct — it fails toward re-registration, never
# toward keeping a stale key.
openclaw_mcp_state() {
  local out
  out="$(openclaw mcp show metronix 2>/dev/null)" || { echo none; return 0; }
  if printf '%s' "$out" | grep -qF "\"$H_URL\"" \
     && printf '%s' "$out" | grep -qF "$H_KEY" \
     && printf '%s' "$out" | grep -qF "$H_AGENT"; then
    echo has_current
  else
    echo has_different
  fi
}

# connect_openclaw(): OpenClaw's equivalent of connect_hermes(). Registers
# Metronix as an MCP server via OpenClaw's own CLI (schema stays correct even if
# the JSON5 shape changes — we never write the file by hand), then appends the
# same runtime-neutral "Metronix is available" marker block Hermes uses to
# OpenClaw's SOUL.md. Falls back to the generic, prompt-based guide on every
# detection gap or CLI failure — the user's files are never left half-edited.
connect_openclaw() {
  local printed="${AGENT_CONN_RESOLVED:-}"
  resolve_agent_connection

  local prompt_dir="./metronix-openclaw-setup"

  if [[ -z "$H_KEY" ]]; then
    warn "No METRONIX_MCP_API_KEY in .env — cannot wire an agent without it."
    write_generic_prompt_dir "$prompt_dir"; return 0
  fi
  if ! openclaw_found; then
    info "OpenClaw not found (\$HOME/.openclaw). Writing a setup guide to apply later."
    write_generic_prompt_dir "$prompt_dir"; return 0
  fi

  info "Found OpenClaw."
  [[ -z "$printed" ]] && info "Metronix MCP URL: $H_URL"

  local method
  if [[ "$ASSUME_YES" == true ]]; then
    if [[ "$CONNECT_OPENCLAW" == true ]]; then method=edit; else method=guide; fi
  else
    info "Connect OpenClaw to Metronix:"
    info "  1) Edit ~/.openclaw for me — register the MCP server (minimal change)   [default]"
    info "  2) Just write a ready-to-paste guide — I'll apply it myself"
    read -rp "Choose 1 or 2 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
    case "${ans:-1}" in
      1|"") method=edit ;;
      2)    method=guide ;;
      *)    err "Invalid choice: $ans"; exit 1 ;;
    esac
  fi

  if [[ "$method" == guide ]]; then
    write_generic_prompt_dir "$prompt_dir"
    info "Paste each into OpenClaw in order (1 install, 2 memory policy, 3 migrate)."
    return 0
  fi

  if ! openclaw_cli_available; then
    warn "Editing openclaw.json safely needs the openclaw CLI, and it isn't on PATH —"
    warn "writing a ready-to-paste guide instead so your file isn't touched."
    write_generic_prompt_dir "$prompt_dir"; return 0
  fi

  local state; state="$(openclaw_mcp_state)"
  if [[ "$state" == has_current ]]; then
    info "Metronix is already present in openclaw.json with the current key — leaving it unchanged."
  else
    if ! openclaw mcp set metronix "$(openclaw_mcp_json)" >/dev/null 2>&1; then
      warn "Could not register Metronix via 'openclaw mcp set' —"
      warn "writing a ready-to-paste guide instead so your file isn't touched."
      write_generic_prompt_dir "$prompt_dir"; return 0
    fi
    if ! openclaw mcp show metronix 2>/dev/null | grep -qF "$H_URL"; then
      warn "'openclaw mcp set' reported success but the URL could not be verified afterward — check ~/.openclaw/openclaw.json."
    fi
    ok "Registered Metronix as an MCP server in OpenClaw."
  fi

  local soul="$HOME/.openclaw/workspace/SOUL.md"
  mkdir -p "$HOME/.openclaw/workspace"
  _backup_file "$soul"
  merge_soul_block "$soul"
  ok "Wired Metronix into OpenClaw (agent_id=$H_AGENT, workspace=$H_WS)."
  write_generic_prompt_dir "$prompt_dir" || true
  info "Restart OpenClaw so the metronix_* tools load. Then paste prompts 2 and 3 from"
  info "  $prompt_dir/ to make Metronix the mandatory memory store and migrate existing memory."
}

# Top-level agent-connection step. Picks the runtime, then routes: Hermes,
# Claude Code, Codex, and OpenClaw get their auto-edit/guide flows; any other MCP
# client gets the filled, runtime-agnostic setup prompts. The four connection
# values are identical for every runtime, so print them up front.
connect_agent() {
  resolve_agent_connection

  info ""
  info "Connect an agent. Every MCP client needs the same four values:"
  info "  MCP URL      : $H_URL"
  info "  API key      : ${H_KEY:-<missing - set METRONIX_MCP_API_KEY in .env>}"
  info "  Agent id     : $H_AGENT"
  info "  Workspace id : $H_WS"
  info ""
  info "Setup walkthrough (auto and prompt-based paths): connecting_to_agent.md"
  info "Ready-to-paste prompts with the values above:    prompts.md"

  # Non-interactive runs keep the existing behavior: --connect-claude/--connect-codex
  # pick that runtime, otherwise go straight to the Hermes step (-y and
  # --connect-hermes are handled inside connect_hermes; this preserves the historical
  # default). --connect-openclaw -y never reaches this branch — main()'s own
  # CONNECT_OPENCLAW && ASSUME_YES shortcut intercepts and exits before connect_agent().
  if [[ "$ASSUME_YES" == true ]]; then
    if [[ "$CONNECT_CLAUDE" == true ]]; then connect_claude_code;
    elif [[ "$CONNECT_CODEX" == true ]]; then connect_codex;
    else connect_hermes; fi
    return 0
  fi

  info ""
  info "Which agent do you want to connect?"
  info "  1) Hermes - edit ~/.hermes for me, or generate paste-ready prompts   [default]"
  info "  2) Claude Code - run 'claude mcp add' for me, or generate paste-ready prompts"
  info "  3) Codex - edit ~/.codex/config.toml for me, or generate paste-ready prompts"
  info "  4) OpenClaw - edit ~/.openclaw for me, or generate paste-ready prompts"
  info "  5) Another MCP client (Cursor, Claude Desktop, ...) - generate paste-ready prompts"
  read -rp "Choose 1, 2, 3, 4 or 5 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
  case "${ans:-1}" in
    1|"") connect_hermes ;;
    2)    connect_claude_code ;;
    3)    connect_codex ;;
    4)    connect_openclaw ;;
    5)    write_generic_prompt_dir "./metronix-agent-setup" ;;
    *)    err "Invalid choice: $ans"; exit 1 ;;
  esac
}

# Return the value .env.example ships for a given key (empty if absent).
# Strips trailing inline comments so the placeholder check matches bare values.
example_val() {
  grep -E "^$1=" "$EXAMPLE_FILE" 2>/dev/null | head -1 | cut -d= -f2- \
    | sed 's/[[:space:]]#.*//' | sed 's/[[:blank:]]*$//'
}

# Is $2 a real, reusable value for secret $1 — i.e. something safe to KEEP instead of
# regenerating? True iff it is non-blank AND not the shipped .env.example placeholder.
# (For the DB keys .env.example ships no value, so this degenerates to "non-blank" — a
# blank/lost DB password is the only unrecoverable case.) Shared by resolve_secret()
# (regenerate unless recoverable) and orphan_db_volume() (a volume is only an orphan
# when its password is NOT recoverable) so the two predicates can't drift apart.
is_recoverable_secret() {
  local key="$1" prev="$2"
  [[ -n "$prev" && "$prev" != "$(example_val "$key")" ]]
}

# Regenerate ($3) unless prev is a recoverable value the user set (non-blank, not the
# .env.example placeholder) — we never rotate a live secret that's already in .env.
resolve_secret() {
  local key="$1" prev="$2" gen="$3"
  if is_recoverable_secret "$key" "$prev"; then printf '%s' "$prev"; else printf '%s' "$gen"; fi
}

# Fill any BLANK required secret in $ENV_FILE in place, and strip an empty
# NEO4J_AUTH= line. Idempotent: existing non-blank values are left untouched (so
# we never rotate a live DB password). This guards every path that launches an
# *existing* .env without a full reconfigure (resume start/rebuild, fixenv) so
# the stack can never come up with a missing METRONIX_MCP_API_KEY / DB secret —
# the case where connect_hermes later reports "No METRONIX_MCP_API_KEY in .env".
# Aborts if a generator yields nothing (no openssl and no readable /dev/urandom).
backfill_env_secrets() {
  # An empty NEO4J_AUTH= overrides compose's default and breaks Neo4j startup.
  if grep -qE "^NEO4J_AUTH=$" "$ENV_FILE" 2>/dev/null; then
    grep -v '^NEO4J_AUTH=$' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
    ok "Removed empty NEO4J_AUTH= from $ENV_FILE"
  fi
  # Never fill a BLANK DB password with a fresh random value when that database's data
  # volume already exists — the volume keeps its first-start password, so the new one
  # would be rejected. Stop with guidance instead (same guard as configure()).
  assert_recoverable_db_passwords "$(get_env NEO4J_PASSWORD)" "$(get_env POSTGRES_PASSWORD)" "$ENV_FILE"
  local k prev val
  for k in POSTGRES_PASSWORD NEO4J_PASSWORD METRONIX_MCP_API_KEY FERNET_KEY; do
    prev="$(get_env "$k")"
    [[ -n "$prev" ]] && continue
    if [[ "$k" == FERNET_KEY ]]; then val="$(gen_fernet)"; else val="$(gen_secret)"; fi
    if [[ -z "$val" ]]; then
      err "Could not generate a value for $k (need openssl or a readable /dev/urandom). Aborting before launch."
      exit 1
    fi
    set_env "$k" "$val"
    ok "Generated missing $k"
  done
}

configure() {
  if [[ -f "$ENV_FILE" && "$RECONFIGURE" == false ]]; then
    ok ".env already exists — reusing it (use --reconfigure to redo)"
    return 0
  fi

  if [[ "$ASSUME_YES" == false && ! -t 0 ]]; then
    err "No terminal for interactive prompts. Re-run with -y/--yes (and, for mode=answers, pass --chat-url plus --chat-model and optionally --chat-api-key), or run from an interactive shell."
    exit 2
  fi

  # Preserve secrets across --reconfigure (don't rotate live DB passwords).
  local prev_pg prev_neo prev_mcp prev_fernet prev_secret
  prev_pg="$(get_env POSTGRES_PASSWORD)"
  prev_neo="$(get_env NEO4J_PASSWORD)"
  prev_mcp="$(get_env METRONIX_MCP_API_KEY)"
  prev_fernet="$(get_env FERNET_KEY)"
  prev_secret="$(get_env METRONIX_SECRET_KEY)"

  # A DB password is only meaningful while its data volume still exists — Neo4j and
  # Postgres fix it on FIRST start and never rotate it, and the volume holds the only
  # copy the database will accept. So derive keep-vs-regenerate from real volume state,
  # not a hand-set flag: when the volume is GONE (fresh install, a full reset that
  # actually removed it, a manual `down -v`), any password left in .env is stale — drop
  # it so resolve_secret() below regenerates it. When the volume EXISTS, keep the
  # password (rotating it would guarantee a mismatch). Any path that wipes the volumes
  # therefore gets fresh DB passwords automatically, so the "reset did nothing" bug
  # can't recur just because a new reset path forgot to set a flag.
  # (If Docker can't be queried here the probe is empty and we blank — harmless, since
  # the guard below re-probes and aborts before any password is written.)
  [[ -z "$(probe_db_volume full_pg_data)" ]] && prev_pg=""
  [[ -z "$(probe_db_volume full_neo4j_data)" ]] && prev_neo=""

  [[ -f "$EXAMPLE_FILE" ]] || { err "$EXAMPLE_FILE not found in $(pwd)"; exit 1; }

  # Before generating any secrets, refuse to proceed if an existing DB data volume
  # would guarantee an auth mismatch (reinstall with a lost/blank password). Doing
  # this before staging the temp .env means an abort leaves nothing half-written.
  assert_recoverable_db_passwords "$prev_neo" "$prev_pg" "$ENV_FILE"

  # Stage the new config in a temp file and promote it to $ENV_FILE only after
  # everything validates. A partial or aborted run (e.g. a blank required field)
  # must never leave a half-written .env behind — otherwise the next run sees an
  # existing .env, skips all prompts, and launches with a broken config.
  local final_env="$ENV_FILE"
  ENV_FILE="$(mktemp "${final_env}.XXXXXX")"
  trap 'rm -f "$ENV_FILE"' EXIT
  cp "$EXAMPLE_FILE" "$ENV_FILE"

  info "Vector embeddings run locally on the bundled Ollama (model: nomic-embed-text)."
  info "Knowledge-graph extraction and local answers run on the bundled Ollama (model: qwen2.5:3b),"
  info "pulled automatically on first start. No external LLM is required by default."
  info "The choice below is only about answer generation (chat)."
  info ""

  # Pick the scenario: pure memory store vs. Metronix generating answers itself.
  if [[ -z "$MODE" ]]; then
    if [[ "$ASSUME_YES" == true ]]; then
      # Non-interactive: a chat endpoint implies "answers"; otherwise "memory".
      if [[ -n "$CHAT_URL" ]]; then MODE=answers; else MODE=memory; fi
    else
      info "How will you use Metronix?"
      info "  1) As a memory store for your own agent, e.g. Hermes   [default]"
      info "       The agent reads/writes memories and generates its own answers."
      info "       No chat model is needed here."
      info "  2) Standalone — Metronix generates the answers itself"
      info "       You will point it at a chat-model endpoint next."
      info ""
      read -rp "Choose 1 or 2 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
      case "${ans:-1}" in
        1|"") MODE=memory ;;
        2)    MODE=answers ;;
        *)    err "Invalid choice: $ans"; exit 1 ;;
      esac
    fi
  fi
  case "$MODE" in
    memory|answers) ;;
    *) err "Unsupported --mode: $MODE. Use 'memory' or 'answers'."; exit 1 ;;
  esac

  if [[ "$MODE" == answers ]]; then
    # One OpenAI-compatible endpoint covers everything: a local Ollama via its
    # /v1 path, a self-hosted vLLM/LocalAI, or a cloud API. URL and model are
    # required; the token is optional (blank = an internal endpoint with no auth).
    if [[ -z "$CHAT_URL" ]]; then
      [[ "$ASSUME_YES" == true ]] && { err "mode=answers requires a chat endpoint (--chat-url)"; exit 1; }
      info "Chat-model endpoint (OpenAI-compatible)."
      info "Examples: http://host.docker.internal:11434/v1 (a local Ollama), https://api.deepseek.com/v1"
      prompt_required CHAT_URL "Endpoint URL: "
    fi
    if [[ -z "$CHAT_MODEL" ]]; then
      [[ "$ASSUME_YES" == true ]] && { err "mode=answers requires a model name (--chat-model)"; exit 1; }
      prompt_required CHAT_MODEL "Model name (e.g. llama3.1:8b, deepseek-chat): "
    fi
    if [[ -z "$CHAT_API_KEY" && "$ASSUME_YES" == false ]]; then
      # Optional on purpose: a local/internal endpoint may need no authentication.
      read -rsp "API key (leave blank for a local/internal endpoint with no auth): " CHAT_API_KEY \
        || { echo; err "Aborted (no input)."; exit 1; }
      echo
    fi
    set_env LLM_PROVIDER custom
    set_env LLM_PROVIDER_URL "$CHAT_URL"
    set_env LLM_PROVIDER_MODEL "$CHAT_MODEL"
    set_env LLM_PROVIDER_API_KEY "$CHAT_API_KEY"
    ok "Answer generation -> $CHAT_URL (model: $CHAT_MODEL)"
  else
    # Memory store: the connected agent does the answering. The bundled Ollama
    # still runs a small local model (OLLAMA_LLM_MODEL) for graph extraction.
    set_env LLM_PROVIDER ollama
    ok "Memory-store mode — answers come from the connected agent."
  fi

  # Open WebUI is a chat front-end — it only works once Metronix can generate
  # answers itself (mode=answers). In memory-store mode there is no chat model,
  # so it is skipped entirely; a stray --openwebui there is ignored with a warning.
  if [[ "$MODE" != answers ]]; then
    if [[ "$ENABLE_WEBUI" == true ]]; then
      warn "Open WebUI needs a chat model — ignoring --openwebui in memory-store mode (use --mode answers)."
      ENABLE_WEBUI=false
    fi
  elif [[ "$ENABLE_WEBUI" == false && "$ASSUME_YES" == false ]]; then
    # Answers mode: a chat UI is almost always wanted, so default to yes.
    read -rp "Enable Open WebUI chat interface (:$WEBUI_PORT)? [Y/n]: " ans \
      || { err "Aborted (no input)."; exit 1; }
    [[ "$ans" =~ ^[Nn] ]] || ENABLE_WEBUI=true
  fi

  # Metronix Admin Console — a web admin panel for connecting data sources and chat-bot
  # channels, uploading files, and monitoring service/database health. It talks to
  # the REST API only (no chat model), so it works in any mode and is offered
  # unconditionally. With --admin or -y it is enabled/skipped without prompting.
  if [[ "$ENABLE_ADMIN" == false && "$ASSUME_YES" == false ]]; then
    read -rp "Install the Metronix Admin Console (web admin panel)? [Y/n]: " ans \
      || { err "Aborted (no input)."; exit 1; }
    if [[ ! "$ans" =~ ^[Nn] ]]; then
      ENABLE_ADMIN=true
      # Default host port is 3000; let the user pick another (e.g. if it's taken).
      local admin_port_ans
      while true; do
        read -rp "Metronix Admin Console port [default $ADMIN_PORT]: " admin_port_ans \
          || { err "Aborted (no input)."; exit 1; }
        [[ -z "$admin_port_ans" ]] && break
        if [[ "$admin_port_ans" =~ ^[0-9]+$ && "$admin_port_ans" -ge 1 && "$admin_port_ans" -le 65535 ]]; then
          ADMIN_PORT="$admin_port_ans"; break
        fi
        warn "Enter a port number between 1 and 65535 (or press Enter for $ADMIN_PORT)."
      done
    fi
  fi
  # Persist the host port so docker compose substitutes ${ADMIN_FRONTEND_PORT}.
  # (Legacy KB_FRONTEND_PORT is still honored by compose as a fallback for one release.)
  [[ "$ENABLE_ADMIN" == true ]] && set_env ADMIN_FRONTEND_PORT "$ADMIN_PORT"

  # Resolve secrets into plain variables first. A failed generator inside the
  # nested $(...) of a set_env call does NOT trip `set -e` — it just yields an
  # empty string, and set_env would happily write "KEY=" and return 0. So we
  # compute the values, then explicitly refuse to proceed if any came out blank
  # (e.g. neither openssl nor /dev/urandom produced output).
  # METRONIX_SECRET_KEY signs JWTs (used when AUTH_ENABLED=true). It ships with a
  # publicly-known placeholder ("develop-secret-key-change-in-prod"), so rotate it
  # to a random value on a fresh install. resolve_secret keeps a real user value
  # (anything other than blank or the shipped placeholder) untouched.
  local val_pg val_neo val_mcp val_fernet val_secret
  val_pg="$(resolve_secret POSTGRES_PASSWORD "$prev_pg" "$(gen_secret)")"
  val_neo="$(resolve_secret NEO4J_PASSWORD "$prev_neo" "$(gen_secret)")"
  val_mcp="$(resolve_secret METRONIX_MCP_API_KEY "$prev_mcp" "$(gen_secret)")"
  val_fernet="$(resolve_secret FERNET_KEY "$prev_fernet" "$(gen_fernet)")"
  val_secret="$(resolve_secret METRONIX_SECRET_KEY "$prev_secret" "$(gen_secret)")"

  local _pair
  for _pair in "POSTGRES_PASSWORD:$val_pg" "NEO4J_PASSWORD:$val_neo" \
               "METRONIX_MCP_API_KEY:$val_mcp" "FERNET_KEY:$val_fernet" \
               "METRONIX_SECRET_KEY:$val_secret"; do
    if [[ -z "${_pair#*:}" ]]; then
      err "Could not generate a value for ${_pair%%:*} (need openssl or a readable /dev/urandom). Aborting before launch."
      exit 1
    fi
  done

  set_env POSTGRES_PASSWORD "$val_pg"
  set_env NEO4J_PASSWORD "$val_neo"
  set_env METRONIX_MCP_API_KEY "$val_mcp"
  set_env FERNET_KEY "$val_fernet"
  set_env METRONIX_SECRET_KEY "$val_secret"

  # Remove NEO4J_AUTH if it is empty — an empty string overrides docker-compose's
  # default of "neo4j/<password>", causing Neo4j to reject the initial credentials.
  if grep -qE "^NEO4J_AUTH=$" "$ENV_FILE" 2>/dev/null; then
    grep -v '^NEO4J_AUTH=$' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
  fi

  # Everything validated — promote the staged config atomically and disarm the
  # cleanup trap so the real .env survives.
  mv "$ENV_FILE" "$final_env"
  trap - EXIT
  ENV_FILE="$final_env"
  ok "Wrote $ENV_FILE"
}

# The core services we expect to be running (container_name:healthy-or-not).
CORE_CONTAINERS=(
  metronix-full-postgres metronix-full-qdrant metronix-full-neo4j
  metronix-full-redis metronix-full-ollama metronix-full-splade
  metronix-full-api
)

# The Compose project name for THIS checkout. Compose prefixes every volume with it
# (<project>_<short>, e.g. metronix-memory_full_neo4j_data); with no `name:` in
# docker-compose.yml it defaults to the checkout directory name (lowercased, with
# anything outside [a-z0-9_-] stripped). $COMPOSE_PROJECT_NAME overrides it — and real
# `docker compose` honors that override from .env as well as the shell environment, so
# this must too, or a user who sets it in .env (rather than exporting it) would get a
# silently WRONG project name here, causing probe_db_volume() to miss their volume
# entirely (false "no volume", the exact mismatch this guard exists to prevent) rather
# than just falling back to the directory-name guess. We need the exact name to scope
# volume lookups below — a bare suffix match would also catch ANOTHER checkout's
# volumes (e.g. a colleague's differently-named clone on the same Docker daemon) and
# false-abort a legitimate fresh install.
compose_project_name() {
  if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
    printf '%s' "$COMPOSE_PROJECT_NAME"
    return
  fi
  local from_env; from_env="$(get_env COMPOSE_PROJECT_NAME)"
  if [[ -n "$from_env" ]]; then
    printf '%s' "$from_env"
    return
  fi
  basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'
}

# Resolve a Compose short volume name (e.g. full_neo4j_data) to the real Docker volume
# name, scoped to THIS project. Prints the name when it exists, nothing when it does
# not; returns 0 in either case (so `name=$(probe_db_volume ...)` under `set -e` never
# aborts the caller). Returns 2 ONLY when Docker itself could not be queried — that
# distinct code matters: a transient daemon failure must NEVER be misread as "no volume",
# because callers would then write a fresh random password onto a volume that still has
# the old one (the exact bug this guard exists to prevent). Existence is therefore told
# by whether a name is printed; "Docker unreachable" is told by rc=2. Prefers the
# project-prefixed name; falls back to an unprefixed `docker volume inspect`.
probe_db_volume() {
  local short="$1" proj out rc match
  [[ -n "$short" ]] || return 1
  out="$(docker volume ls --format '{{.Name}}' 2>/dev/null)"; rc=$?
  [[ $rc -eq 0 ]] || return 2
  proj="$(compose_project_name)"
  if [[ -n "$proj" ]]; then
    match="$(printf '%s\n' "$out" | grep -Fx -- "${proj}_${short}" | head -1 || true)"
  else
    match="$(printf '%s\n' "$out" | grep -E -- "_${short}\$" | head -1 || true)"   # unknown project: legacy suffix match
  fi
  [[ -z "$match" ]] && docker volume inspect "$short" >/dev/null 2>&1 && match="$short"
  [[ -n "$match" ]] && printf '%s' "$match"
  return 0
}

# Tolerant wrapper around probe_db_volume for informational callers (launch/diagnose):
# print the real name if present, otherwise nothing, and always return 0 so
# `var=$(resolve_volume_name ...)` under `set -e` never aborts the caller. A Docker
# failure is intentionally collapsed to empty here — the strict guard handles it.
resolve_volume_name() {
  local short="$1" name
  [[ -n "$short" ]] || return 0
  name="$(probe_db_volume "$short")"   # ignore rc: empty == absent-or-unreachable
  [[ -n "$name" ]] && printf '%s' "$name"
  return 0
}

# Detect a DB data volume that would guarantee an auth mismatch: the volume exists but
# its password is NOT recoverable (blank/lost in .env), so any freshly generated
# password is certain to be rejected. Echoes the real volume name on conflict, else
# nothing. Returns 0 normally; returns 2 to propagate "Docker unreachable" so the
# guard can abort loudly rather than mistaking it for "no conflict".
# Args: <compose-short-volume> <env-key> <prev-value>.
orphan_db_volume() {
  local short="$1" key="$2" prev="$3" name rc=0
  # A recoverable previous password means no conflict — resolve_secret keeps it (or the
  # user restored it), so what we write matches the volume.
  is_recoverable_secret "$key" "$prev" && return 0
  name="$(probe_db_volume "$short")" || rc=$?
  [[ $rc -eq 2 ]] && return 2
  [[ -n "$name" ]] && printf '%s' "$name"
  return 0
}

# Print the "could not query Docker" error and exit. Used when a volume probe returns
# rc=2: a failed probe must never be treated as "no conflict" (see probe_db_volume).
docker_probe_failed() {
  err "Could not query Docker for the $1 data volume (the daemon may be down or"
  err "momentarily unreachable). Refusing to proceed: if this were misread as 'no"
  err "volume', a fresh DB password would be written onto an existing volume and the"
  err "stack would come up broken — the exact failure this guard prevents."
  err "Re-run once Docker is reachable."
  exit 1
}

# Guard used by configure()/backfill_env_secrets(): refuse to write a fresh random DB
# password when a data volume from a previous install still exists but its password is
# unrecoverable — launching would fail auth on startup. $3 is the real .env path to
# name in the guidance (configure stages into a temp file). Exits 1 on conflict OR when
# Docker itself can't be queried; returns 0 otherwise.
assert_recoverable_db_passwords() {
  local prev_neo="$1" prev_pg="$2" target="${3:-$ENV_FILE}"
  local orphan_neo="" orphan_pg="" rc_neo=0 rc_pg=0
  orphan_neo="$(orphan_db_volume full_neo4j_data NEO4J_PASSWORD "$prev_neo")" || rc_neo=$?
  orphan_pg="$(orphan_db_volume full_pg_data POSTGRES_PASSWORD "$prev_pg")" || rc_pg=$?
  [[ $rc_neo -eq 2 ]] && docker_probe_failed "Neo4j"
  [[ $rc_pg -eq 2 ]]  && docker_probe_failed "Postgres"
  [[ -z "$orphan_neo" && -z "$orphan_pg" ]] && return 0

  err "A database data volume from a previous install already exists, but its password"
  err "cannot be recovered from $target. Neo4j/Postgres fix the password on FIRST start"
  err "and never change it on an existing volume, so a new random password would be"
  err "rejected and the stack would come up broken."
  [[ -n "$orphan_neo" ]] && err "  Neo4j volume:    $orphan_neo"
  [[ -n "$orphan_pg" ]]  && err "  Postgres volume: $orphan_pg"
  err ""
  err "Choose one:"
  err "  - Keep the data: put the ORIGINAL password back in $target, then rerun ./install.sh -y"
  err "  - Discard the data (DESTROYS it): ${COMPOSE[*]} -f $COMPOSE_FILE down -v && ./install.sh -y --reconfigure"
  exit 1
}

# Check the health of one container. Echo: up:healthy | up:unhealthy | up:starting
# | down | missing. Never errors.
container_status() {
  local c="$1" s
  if ! docker inspect "$c" >/dev/null 2>&1; then echo missing; return; fi
  s="$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null)"
  if [[ "$s" != "running" ]]; then echo down; return; fi
  # Has a healthcheck?
  local hs; hs="$(docker inspect --format '{{.State.Health.Status}}' "$c" 2>/dev/null)"
  case "$hs" in
    healthy)   echo up:healthy ;;
    unhealthy) echo up:unhealthy ;;
    starting)  echo up:starting ;;
    *)         echo up:unknown ;;  # no healthcheck or blank
  esac
}

# Print the status of every core container in a compact table.
diagnose_state() {
  local env_exists=no env_issues="" any_exist=no any_unhealthy=no

  # If COMPOSE was never detected (e.g. check_prereqs stubbed in tests), skip
  # the volume/compose introspection but still report what we can.
  local compose_ok=yes
  [[ ${#COMPOSE[@]} -eq 0 ]] && compose_ok=no

  info "━━━ Inspecting current installation state ━━━"
  info ""

  # -- .env existence + common breakage --
  if [[ -f "$ENV_FILE" ]]; then
    env_exists=yes
    # Check for known breakage: empty NEO4J_AUTH=
    if grep -qE '^NEO4J_AUTH=$' "$ENV_FILE" 2>/dev/null; then
      env_issues+="NEO4J_AUTH is set to an empty string (breaks Neo4j startup); "
    fi
    # Check for missing required secrets (blank POSTGRES_PASSWORD etc.)
    local k v
    for k in POSTGRES_PASSWORD NEO4J_PASSWORD METRONIX_MCP_API_KEY FERNET_KEY; do
      v="$(grep -E "^${k}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
      if [[ -z "$v" ]]; then env_issues+="${k} is blank; "; fi
    done
    if [[ -z "$env_issues" ]]; then
      ok ".env exists  ($ENV_FILE)"
    else
      warn ".env exists but has issues: ${env_issues%; }"
    fi
  else
    warn ".env NOT found  ($ENV_FILE)"
  fi

  # -- Container status table --
  info ""
  info "Service status:"
  local c st
  for c in "${CORE_CONTAINERS[@]}"; do
    st="$(container_status "$c")"
    case "$st" in
      up:healthy)   printf '  %s%-22s%s %s healthy%s\n' "$C_OK" "$c" "$C_RST" "$C_OK" "$C_RST" ;;
      up:unhealthy) printf '  %s%-22s%s %sunhealthy%s\n' "$C_OK" "$c" "$C_RST" "$C_ERR" "$C_RST"; any_unhealthy=yes ;;
      up:starting)  printf '  %s%-22s%s %s starting…%s\n' "$C_OK" "$c" "$C_RST" "$C_WARN" "$C_RST" ;;
      up:unknown)   printf '  %s%-22s%s running (no healthcheck)%s\n' "$C_OK" "$c" "$C_RST" "$C_RST" ;;
      down)         printf '  %s%-22s%s %sexited%s\n' "$C_WARN" "$c" "$C_RST" "$C_WARN" "$C_RST"; any_exist=yes ;;
      missing)      printf '  %-22s not created\n' "$c" ;;
    esac
    [[ "$st" != missing ]] && any_exist=yes
  done
  info ""

  # -- Volume check (Neo4j volume exists with potentially old password) --
  local neo_vol="" neo_vol_real="" vol_exists=no
  if [[ "$compose_ok" == yes ]]; then
    neo_vol="$("${COMPOSE[@]}" -f "$COMPOSE_FILE" config --volumes 2>/dev/null \
      | grep -iE 'neo4j' | head -1 || true)"
    if [[ -n "$neo_vol" ]]; then
      neo_vol_real="$(resolve_volume_name "$neo_vol")"
      if [[ -n "$neo_vol_real" ]]; then
        vol_exists=yes
        info "Neo4j data volume '$neo_vol_real' exists (password set on first startup only)."
      fi
    fi
  fi

  # -- API reachable? --
  local api_ok=no
  if command -v curl >/dev/null 2>&1 && curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
    api_ok=yes; ok "API is reachable at http://localhost:$API_PORT/health"
  else
    warn "API is NOT reachable at http://localhost:$API_PORT/health"
  fi

  # Set globals for the resume menu.
  DIAG_ENV="$env_exists"
  DIAG_ENV_ISSUES="$env_issues"
  DIAG_ANY_EXIST="$any_exist"
  DIAG_ANY_UNHEALTHY="$any_unhealthy"
  DIAG_VOL_EXISTS="$vol_exists"
  DIAG_API_OK="$api_ok"
}

# Offer the user a menu based on what diagnose_state() found. Sets RESUME_ACTION
# to one of: start | rebuild | reconfigure | reset | freshreset | fixenv | exit.
resume_menu() {
  # In -y / non-interactive mode, pick the most reasonable action automatically.
  if [[ "$ASSUME_YES" == true ]]; then
    if [[ "$DIAG_API_OK" == yes ]]; then RESUME_ACTION="exit"; return; fi
    if [[ "$DIAG_ENV" == yes && -n "$DIAG_ENV_ISSUES" ]]; then RESUME_ACTION="fixenv"; return; fi
    if [[ "$DIAG_ANY_EXIST" == yes ]]; then RESUME_ACTION="rebuild"; return; fi
    if [[ "$DIAG_ENV" == yes ]]; then RESUME_ACTION="start"; return; fi
    RESUME_ACTION="reconfigure"; return
  fi

  # Interactive: build a list of relevant options.
  local opts=() labels=() n=0 choice

  info "What would you like to do?"
  info ""

  if [[ "$DIAG_ENV" == yes && -n "$DIAG_ENV_ISSUES" ]]; then
    n=$((n+1)); opts+=("fixenv");       labels+=("Fix .env issues and continue")
  fi
  if [[ "$DIAG_API_OK" == yes ]]; then
    n=$((n+1)); opts+=("exit");         labels+=("Stack is healthy — nothing to do, exit")
  fi
  if [[ "$DIAG_ENV" == yes && "$DIAG_ANY_EXIST" == no ]]; then
    n=$((n+1)); opts+=("start");        labels+=("Start the stack (config exists, containers not created)")
  fi
  if [[ "$DIAG_ANY_EXIST" == yes ]]; then
    n=$((n+1)); opts+=("rebuild");      labels+=("Rebuild and restart the stack")
  fi
  if [[ "$DIAG_ANY_UNHEALTHY" == yes || "$DIAG_VOL_EXISTS" == yes ]]; then
    n=$((n+1)); opts+=("reset");        labels+=("Reset all data volumes and reinstall (destructive)")
  fi
  if [[ "$DIAG_ANY_EXIST" == yes || "$DIAG_VOL_EXISTS" == yes ]]; then
    n=$((n+1)); opts+=("freshreset");   labels+=("Fresh Docker reset: remove containers, images, volumes, build cache")
  fi
  n=$((n+1)); opts+=("reconfigure");    labels+=("Re-run full configuration from scratch")
  n=$((n+1)); opts+=("exit");           labels+=("Exit now")

  local i
  for i in "${!opts[@]}"; do
    printf '  %d) %s\n' "$((i+1))" "${labels[$i]}"
  done
  info ""
  read -rp "Choose [1-$n]: " choice || { err "Aborted."; exit 1; }
  case "$choice" in
    ''|*[!0-9]*) err "Invalid choice: $choice"; exit 1 ;;
  esac
  if [[ "$choice" -lt 1 || "$choice" -gt "$n" ]]; then
    err "Choice out of range: $choice"; exit 1
  fi
  RESUME_ACTION="${opts[$((choice-1))]}"
}

fresh_docker_reset() {
  warn "This will DELETE Metronix Docker containers, images, volumes, and orphan containers."
  warn "It will ALSO prune the ENTIRE Docker build cache on this machine — not just Metronix."
  warn "Data in PostgreSQL, Qdrant, Neo4j, Redis, Ollama, and uploaded files will be removed."
  if [[ "$ASSUME_YES" != true ]]; then
    read -rp "Type 'delete docker data' to confirm: " confirm || { err "Aborted."; exit 1; }
    [[ "$confirm" == "delete docker data" ]] || { err "Aborted."; exit 1; }
  fi

  info "Removing Metronix containers, images, volumes, and orphans..."
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" down -v --rmi all --remove-orphans 2>/dev/null || true

  info "Pruning Docker build cache (machine-wide, all projects)..."
  docker builder prune -af >/dev/null 2>&1 || warn "Could not prune Docker build cache; continuing."
  # The data volumes are gone. configure() regenerates any DB password whose volume no
  # longer exists, so no flag is needed here — see configure() for the rationale.
  ok "Docker resources for Metronix were reset."
}

# Apply the action chosen in resume_menu. May reconfigure, fixenv, launch, etc.
do_resume() {
  case "$RESUME_ACTION" in
    exit)
      ok "Nothing to do — exiting."
      ;;
    fixenv)
      info "Fixing .env issues…"
      backfill_env_secrets
      # Now rebuild/restart so the fix takes effect.
      launch; wait_health; print_links; connect_hermes
      ;;
    start)
      # Backfill any blank secret before launch: an existing .env may be missing
      # METRONIX_MCP_API_KEY etc., which would otherwise come up but leave the
      # agent un-wireable.
      backfill_env_secrets
      launch; wait_health; print_links; connect_hermes
      ;;
    rebuild)
      backfill_env_secrets
      "${COMPOSE[@]}" -f "$COMPOSE_FILE" down 2>/dev/null || true
      launch; wait_health; print_links; connect_hermes
      ;;
    reset)
      warn "This will DELETE all data volumes (PostgreSQL, Qdrant, Neo4j, Redis, Ollama)."
      if [[ "$ASSUME_YES" != true ]]; then
        read -rp "Type 'yes' to confirm: " confirm || { err "Aborted."; exit 1; }
        [[ "$confirm" == "yes" ]] || { err "Aborted."; exit 1; }
      fi
      "${COMPOSE[@]}" -f "$COMPOSE_FILE" down -v 2>/dev/null || true
      # volumes wiped above; configure() regenerates DB passwords whose volume is gone.
      RECONFIGURE=true
      configure
      launch; wait_health; print_links; connect_hermes
      ;;
    freshreset)
      fresh_docker_reset
      RECONFIGURE=true
      configure
      launch; wait_health; print_links; connect_hermes
      ;;
    reconfigure)
      RECONFIGURE=true
      configure
      launch; wait_health; print_links; connect_hermes
      ;;
  esac
}

launch() {
  # Warn if a database volume already exists with a potentially different password.
  # Postgres and Neo4j BOTH set their password only on FIRST startup; on an existing
  # volume they keep the original. If POSTGRES_PASSWORD / NEO4J_PASSWORD in .env has
  # changed since the volume was created, the DB rejects the new credentials —
  # Postgres with "password authentication failed for user ...", Neo4j with an
  # unhealthy container. (Postgres can stay up yet refuse every query, so the stack
  # looks healthy while memory writes silently fail.)
  local neo_vol="" pg_vol=""
  neo_vol="$(resolve_volume_name "$("${COMPOSE[@]}" -f "$COMPOSE_FILE" config --volumes 2>/dev/null | grep -iE 'neo4j' | head -1 || true)")"
  pg_vol="$(resolve_volume_name "$("${COMPOSE[@]}" -f "$COMPOSE_FILE" config --volumes 2>/dev/null | grep -iE 'pg|postgres' | head -1 || true)")"
  if [[ "$RECONFIGURE" == true ]]; then
    local _v _name
    for _v in "POSTGRES_PASSWORD:$pg_vol" "NEO4J_PASSWORD:$neo_vol"; do
      _name="${_v#*:}"
      [[ -n "$_name" ]] || continue
      warn "Database volume '$_name' already exists."
      warn "  Its password was fixed on FIRST startup. If ${_v%%:*} in .env differs"
      warn "  from that value, the database will reject connections."
      warn "  To reset (DESTROYS data): ${COMPOSE[*]} -f $COMPOSE_FILE down -v && ./install.sh -y --reconfigure"
    done
  fi

  local args=(-f "$COMPOSE_FILE")
  [[ "$ENABLE_WEBUI" == true ]] && args+=(--profile openwebui)
  [[ "$ENABLE_ADMIN" == true ]] && args+=(--profile admin)
  args+=(up -d --build)
  info "Building and starting the stack (first run can take 10-15 min)..."
  if ! "${COMPOSE[@]}" "${args[@]}"; then
    warn ""
    warn "Docker Compose failed while starting the stack."
    warn "If Neo4j is unhealthy, the most common cause is an existing Neo4j data"
    warn "volume whose first-start password differs from NEO4J_PASSWORD in .env."
    if [[ -n "$neo_vol" ]]; then
      warn "Detected Neo4j volume: $neo_vol"
    fi
    warn ""
    warn "To keep existing data, restore the original NEO4J_PASSWORD in .env and rerun:"
    warn "  ./install.sh -y"
    warn ""
    warn "To discard local install data and start clean:"
    warn "  ${COMPOSE[*]} -f $COMPOSE_FILE down -v"
    warn "  ./install.sh -y --reconfigure"
    warn ""
    warn "More help (prerequisites, ports, troubleshooting): install.md"
    return 1
  fi
}

# Postgres (and Neo4j) only honour POSTGRES_PASSWORD / NEO4J_PASSWORD on FIRST
# startup; on an existing volume they keep the original. If the .env password later
# differs, Postgres ACCEPTS the container start (healthcheck = pg_isready, which does
# not authenticate) but REJECTS every real query with "password authentication failed
# for user metronix". The API can then report /health OK while every memory write
# fails. Inspect the Postgres log and surface this explicitly. Returns 1 if detected.
warn_if_db_auth_failed() {
  local logs
  logs="$(docker logs --tail 80 metronix-full-postgres 2>&1 || true)"
  if printf '%s' "$logs" | grep -qi 'password authentication failed'; then
    warn ""
    warn "Postgres is rejecting the configured password (\"password authentication failed\")."
    warn "  POSTGRES_PASSWORD in .env no longer matches the password its data volume was"
    warn "  initialised with on first start. The stack can look healthy, but memory writes"
    warn "  (and other DB access) will fail — this is the usual cause of MCP save errors."
    warn "  Fix, restoring the original POSTGRES_PASSWORD in .env, OR reset (DESTROYS data):"
    warn "    ${COMPOSE[*]} -f $COMPOSE_FILE down -v && ./install.sh -y --reconfigure"
    return 1
  fi
  return 0
}

wait_health() {
  command -v curl >/dev/null 2>&1 || { warn "curl not found — skipping health check."; return 0; }
  info "Waiting for the API on :$API_PORT ..."
  local _i healthy=no
  for _i in $(seq 1 60); do
    if curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
      ok "API is healthy"
      healthy=yes
      break
    fi
    sleep 5
  done
  if [[ "$healthy" == no ]]; then
    warn "API did not report healthy within ~5 min. It may still be building."
    warn "  Check logs: ${COMPOSE[*]} -f $COMPOSE_FILE logs -f metronix-core"
    # If Neo4j is unhealthy, give a targeted hint (common: password/volume mismatch).
    if docker inspect --format='{{.State.Health.Status}}' metronix-full-neo4j 2>/dev/null \
       | grep -q unhealthy; then
      warn ""
      warn "Neo4j container is UNHEALTHY. Common causes:"
      warn "  1. NEO4J_AUTH set to empty in .env (remove the line to use the default)"
      warn "  2. NEO4J_PASSWORD changed on an existing volume (reset: docker compose -f $COMPOSE_FILE down -v)"
      warn "  3. NEO4J_PASSWORD is a hash, not plain text (use a plain text password)"
      warn "  Neo4j logs: docker logs metronix-full-neo4j"
    fi
  fi
  # Even when /health is green, Postgres may be rejecting the password on an existing
  # volume — this is silent except in DB logs, so always check.
  warn_if_db_auth_failed
  return 0
}

print_links() {
  info ""
  ok "Metronix Core is up."
  info "  API:          http://localhost:$API_PORT"
  info "  MCP endpoint: http://localhost:$API_PORT/mcp"
  [[ "$ENABLE_ADMIN" == true ]] && info "  Admin Console: https://localhost:$ADMIN_PORT"
  [[ "$ENABLE_WEBUI" == true ]] && info "  Open WebUI:   http://localhost:$WEBUI_PORT"
  info ""
  info "Manage the stack:"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE ps        # status"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE logs -f   # logs"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE down      # stop"
  info ""
  info "Next steps:"
  info "  Connect an agent:        connecting_to_agent.md"
  [[ "$ENABLE_ADMIN" == true ]]    && info "  Metronix Admin Console:  frontend/README.md (login: admin@metronix.local / metronix)"
  [[ "$ENABLE_WEBUI" == true ]] && info "  Open WebUI:              docs/integrations/openwebui.md"
  info "  Ports & troubleshooting: install.md"
}

main() {
  print_banner
  parse_args "$@"
  cd "$REPO_ROOT"
  # Standalone agent-wiring: skip the stack build entirely.
  if [[ "$CONNECT_HERMES" == true && "$ASSUME_YES" == true ]]; then
    [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found — run a full install first, or cd to the deployment dir."; exit 1; }
    connect_hermes
    exit 0
  fi
  if [[ "$CONNECT_CLAUDE" == true && "$ASSUME_YES" == true ]]; then
    [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found — run a full install first, or cd to the deployment dir."; exit 1; }
    connect_claude_code
    exit 0
  fi
  if [[ "$CONNECT_CODEX" == true && "$ASSUME_YES" == true ]]; then
    [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found — run a full install first, or cd to the deployment dir."; exit 1; }
    connect_codex
    exit 0
  fi
  if [[ "$CONNECT_OPENCLAW" == true && "$ASSUME_YES" == true ]]; then
    [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found — run a full install first, or cd to the deployment dir."; exit 1; }
    connect_openclaw
    exit 0
  fi
  check_prereqs

  if [[ "$FRESH_DOCKER_RESET" == true ]]; then
    fresh_docker_reset
    RECONFIGURE=true
  fi

  # Detect existing installation state and offer a resume menu instead of
  # blindly reconfiguring/launching on every run. Only run the diagnosis when
  # there are signs of a previous attempt: .env exists, or containers exist.
  local has_env=no
  [[ -f "$ENV_FILE" ]] && has_env=yes

  if [[ "$has_env" == yes ]]; then
    diagnose_state
    # If everything is already healthy and API is up, the user may just want status.
    if [[ "$DIAG_API_OK" == yes && "$RECONFIGURE" != true ]]; then
      resume_menu; do_resume; exit 0
    fi
    # If there are containers or volumes but config has issues, offer the menu.
    if [[ "$DIAG_ANY_EXIST" == yes || -n "$DIAG_ENV_ISSUES" ]] && [[ "$RECONFIGURE" != true ]]; then
      resume_menu; do_resume; exit 0
    fi
  fi

  # Fresh install path (no .env, no containers) — or --reconfigure forced.
  configure
  launch
  wait_health
  print_links
  connect_agent
}

# Allow sourcing for tests without running main.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
