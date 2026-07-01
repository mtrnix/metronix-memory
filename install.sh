#!/usr/bin/env bash
# Metronix Core installer — builds and starts the full stack from source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"
EXAMPLE_FILE=".env.example"
API_PORT=8000
WEBUI_PORT=3080
KB_PORT="${KB_FRONTEND_PORT:-3000}"   # honor KB_FRONTEND_PORT override (compose uses the same)

MODE=""              # "memory" | "answers" (how Metronix is used)
CHAT_URL=""          # OpenAI-compatible chat-model endpoint (answers mode)
CHAT_MODEL=""        # model name the endpoint serves (answers mode)
CHAT_API_KEY=""      # bearer token for the endpoint (optional; blank = no auth)
ENABLE_WEBUI=false
ENABLE_KB=false      # install the KB Admin Console web UI (profile kb)
ASSUME_YES=false
RECONFIGURE=false
FRESH_DOCKER_RESET=false
WIRE_HERMES=false    # run the Hermes wiring step (and, with -y, apply without prompt)
AGENT_ID=""          # override the generated X-Agent-Id (Hermes wiring)
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

 __  __ ___ _____ ___  ___  _  _ _____  __  __  __ ___ __  __  ___  _____   __
|  \/  | __|_   _| _ \/ _ \| \| |_ _\ \/ / |  \/  | __|  \/  |/ _ \| _ \ \ / /
| |\/| | _|  | | |   / (_) | .` || | >  <  | |\/| | _|| |\/| | (_) |   /\ V /
|_|  |_|___| |_| |_|_\\___/|_|\_|___/_/\_\ |_|  |_|___|_|  |_|\___/|_|_\ |_|

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
  --kb                     Install the KB Admin Console web UI (:3000)
  --wire-hermes            Connect the Hermes agent to Metronix (edit ~/.hermes
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
      --wire-hermes)   WIRE_HERMES=true; shift ;;
      --agent-id)      [[ $# -ge 2 ]] || { err "--agent-id requires a value"; exit 2; }; AGENT_ID="$2"; shift 2 ;;
      --metronix-url)  [[ $# -ge 2 ]] || { err "--metronix-url requires a value"; exit 2; }; METRONIX_URL="$2"; shift 2 ;;
      --openwebui)   ENABLE_WEBUI=true; shift ;;
      --kb)          ENABLE_KB=true; shift ;;
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

# Resolve the agent id, in priority order:
#   1. explicit --agent-id (operator override)
#   2. the X-Agent-Id already in the live Hermes config (source of truth for the
#      running agent — its memories are stored under this id)
#   3. METRONIX_AGENT_ID persisted in .env (installer's durable record; survives a
#      wiped/reset Hermes config so the agent keeps the same id, and thus the same
#      memories, across re-runs)
#   4. a freshly generated id
# The backend never reads an agent id from env — it comes from the X-Agent-Id
# request header — so METRONIX_AGENT_ID is purely the installer's own anchor.
# wire_hermes() persists the resolved value back to .env.
resolve_agent_id() {
  local config="$1" existing persisted
  if [[ -n "$AGENT_ID" ]]; then printf '%s' "$AGENT_ID"; return 0; fi
  if [[ -f "$config" ]]; then
    existing="$(grep -E '^[[:space:]]*X-Agent-Id:' "$config" 2>/dev/null | head -1 | sed -E 's/.*X-Agent-Id:[[:space:]]*//' | tr -d '"' | tr -d '[:space:]')"
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

# Write the ready-to-paste Hermes prompts (filled) into a directory. Prompts 1-3
# are the forward flow (install -> mandatory memory -> migrate); prompt 4 is an
# optional rollback that undoes prompt 2.
# Returns 1 if no templates were found (e.g. install.sh run outside the repo).
write_hermes_prompt_dir() {
  local dir="$1" tdir="$REPO_ROOT/docs/integrations/hermes" found=0 pair src out
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
  ok "Wrote $found ready-to-paste Hermes prompt(s) to $dir/ (apply 1 -> 2 -> 3 in order; 4 is an optional rollback of 2)."
  info "Full Hermes setup guide: docs/integrations/hermes.md"
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

# Back up a file to <file>.bak-<ts> before editing.
_backup_file() { [[ -f "$1" ]] && cp "$1" "$1.bak-$(date +%Y%m%d%H%M%S)"; }

# Resolve the four agent-connection values once and anchor the agent id in .env.
# Idempotent (guarded): connect_agent resolves first, and the default Hermes
# choice then calls wire_hermes — without the guard that would recompute the
# same values and rewrite METRONIX_AGENT_ID. Also covers the standalone
# wire_hermes path (--wire-hermes -y), which never goes through connect_agent.
resolve_agent_connection() {
  [[ -n "${AGENT_CONN_RESOLVED:-}" ]] && return 0
  local config="$HOME/.hermes/config.yaml"
  H_KEY="$(get_env METRONIX_MCP_API_KEY)"
  H_WS="$(get_env DEFAULT_WORKSPACE_ID)"; H_WS="${H_WS:-MTRNIX}"
  H_URL="${METRONIX_URL:-http://localhost:8000/mcp}"
  H_AGENT="$(resolve_agent_id "$config")"
  # Anchor the agent id in .env so re-runs reuse it even if the Hermes config is
  # later reset — keeping the agent's memories under one stable id.
  [[ -f "$ENV_FILE" ]] && set_env METRONIX_AGENT_ID "$H_AGENT"
  AGENT_CONN_RESOLVED=1
}

wire_hermes() {
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
    if [[ "$WIRE_HERMES" == true ]]; then method=edit; else method=guide; fi
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

# Top-level agent-connection step. Picks the runtime, then routes: Hermes gets
# the auto-edit/guide flow (wire_hermes); any other MCP client gets the filled,
# runtime-agnostic setup prompts. The four connection values are identical for
# every runtime, so print them up front.
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

  # Non-interactive runs keep the existing behavior: go straight to the Hermes
  # step (-y and --wire-hermes are handled inside wire_hermes).
  if [[ "$ASSUME_YES" == true ]]; then wire_hermes; return 0; fi

  info ""
  info "Which agent do you want to connect?"
  info "  1) Hermes - edit ~/.hermes for me, or generate paste-ready prompts   [default]"
  info "  2) Another MCP client (Cursor, Claude Desktop/Code, Codex, ...) - generate paste-ready prompts"
  read -rp "Choose 1 or 2 [default: 1]: " ans || { err "Aborted (no input)."; exit 1; }
  case "${ans:-1}" in
    1|"") wire_hermes ;;
    2)    write_generic_prompt_dir "./metronix-agent-setup" ;;
    *)    err "Invalid choice: $ans"; exit 1 ;;
  esac
}

# Return the value .env.example ships for a given key (empty if absent).
# Strips trailing inline comments so resolve_secret matches bare values.
example_val() {
  grep -E "^$1=" "$EXAMPLE_FILE" 2>/dev/null | head -1 | cut -d= -f2- \
    | sed 's/[[:space:]]#.*//' | sed 's/[[:blank:]]*$//'
}

# Regenerate unless prev is a real user value (non-blank and not the .env.example default).
resolve_secret() {
  local key="$1" prev="$2" gen="$3"
  if [[ -z "$prev" || "$prev" == "$(example_val "$key")" ]]; then
    printf '%s' "$gen"
  else
    printf '%s' "$prev"
  fi
}

# Fill any BLANK required secret in $ENV_FILE in place, and strip an empty
# NEO4J_AUTH= line. Idempotent: existing non-blank values are left untouched (so
# we never rotate a live DB password). This guards every path that launches an
# *existing* .env without a full reconfigure (resume start/rebuild, fixenv) so
# the stack can never come up with a missing METRONIX_MCP_API_KEY / DB secret —
# the case where wire_hermes later reports "No METRONIX_MCP_API_KEY in .env".
# Aborts if a generator yields nothing (no openssl and no readable /dev/urandom).
backfill_env_secrets() {
  # An empty NEO4J_AUTH= overrides compose's default and breaks Neo4j startup.
  if grep -qE "^NEO4J_AUTH=$" "$ENV_FILE" 2>/dev/null; then
    grep -v '^NEO4J_AUTH=$' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
    ok "Removed empty NEO4J_AUTH= from $ENV_FILE"
  fi
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

  [[ -f "$EXAMPLE_FILE" ]] || { err "$EXAMPLE_FILE not found in $(pwd)"; exit 1; }

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

  # KB Admin Console — a web admin panel for connecting data sources and chat-bot
  # channels, uploading files, and monitoring service/database health. It talks to
  # the REST API only (no chat model), so it works in any mode and is offered
  # unconditionally. With --kb or -y it is enabled/skipped without prompting.
  if [[ "$ENABLE_KB" == false && "$ASSUME_YES" == false ]]; then
    read -rp "Install the KB Admin Console (web admin panel)? [Y/n]: " ans \
      || { err "Aborted (no input)."; exit 1; }
    if [[ ! "$ans" =~ ^[Nn] ]]; then
      ENABLE_KB=true
      # Default host port is 3000; let the user pick another (e.g. if it's taken).
      local kb_port_ans
      while true; do
        read -rp "KB Admin Console port [default $KB_PORT]: " kb_port_ans \
          || { err "Aborted (no input)."; exit 1; }
        [[ -z "$kb_port_ans" ]] && break
        if [[ "$kb_port_ans" =~ ^[0-9]+$ && "$kb_port_ans" -ge 1 && "$kb_port_ans" -le 65535 ]]; then
          KB_PORT="$kb_port_ans"; break
        fi
        warn "Enter a port number between 1 and 65535 (or press Enter for $KB_PORT)."
      done
    fi
  fi
  # Persist the host port so docker compose substitutes ${KB_FRONTEND_PORT}.
  [[ "$ENABLE_KB" == true ]] && set_env KB_FRONTEND_PORT "$KB_PORT"

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

# Resolve a Compose short volume name (as printed by `config --volumes`, e.g.
# full_neo4j_data) to the real Docker volume name. Compose prefixes volumes with
# the project name (<project>_<short>, e.g. metronix-memory_full_neo4j_data), so a
# bare `docker volume inspect full_neo4j_data` would miss it. Prints the real name
# if a matching volume exists, else nothing. Prefers the project-prefixed volume.
resolve_volume_name() {
  local short="$1" match
  [[ -n "$short" ]] || return 0
  match="$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E "_${short}\$" | head -1 || true)"
  if [[ -z "$match" ]] && docker volume inspect "$short" >/dev/null 2>&1; then
    match="$short"   # fallback: an unprefixed volume actually exists
  fi
  # Always succeed: a "no such volume" result is empty output, not a failure — else
  # `var=$(resolve_volume_name ...)` under set -e would abort the caller (launch()).
  [[ -n "$match" ]] && printf '%s' "$match"
  return 0
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
      launch; wait_health; print_links; wire_hermes
      ;;
    start)
      # Backfill any blank secret before launch: an existing .env may be missing
      # METRONIX_MCP_API_KEY etc., which would otherwise come up but leave the
      # agent un-wireable.
      backfill_env_secrets
      launch; wait_health; print_links; wire_hermes
      ;;
    rebuild)
      backfill_env_secrets
      "${COMPOSE[@]}" -f "$COMPOSE_FILE" down 2>/dev/null || true
      launch; wait_health; print_links; wire_hermes
      ;;
    reset)
      warn "This will DELETE all data volumes (PostgreSQL, Qdrant, Neo4j, Redis, Ollama)."
      if [[ "$ASSUME_YES" != true ]]; then
        read -rp "Type 'yes' to confirm: " confirm || { err "Aborted."; exit 1; }
        [[ "$confirm" == "yes" ]] || { err "Aborted."; exit 1; }
      fi
      "${COMPOSE[@]}" -f "$COMPOSE_FILE" down -v 2>/dev/null || true
      RECONFIGURE=true
      configure
      launch; wait_health; print_links; wire_hermes
      ;;
    freshreset)
      fresh_docker_reset
      RECONFIGURE=true
      configure
      launch; wait_health; print_links; wire_hermes
      ;;
    reconfigure)
      RECONFIGURE=true
      configure
      launch; wait_health; print_links; wire_hermes
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
  [[ "$ENABLE_KB" == true ]] && args+=(--profile kb)
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
  [[ "$ENABLE_KB" == true ]] && info "  KB Console:   http://localhost:$KB_PORT"
  [[ "$ENABLE_WEBUI" == true ]] && info "  Open WebUI:   http://localhost:$WEBUI_PORT"
  info ""
  info "Manage the stack:"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE ps        # status"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE logs -f   # logs"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE down      # stop"
  info ""
  info "Next steps:"
  info "  Connect an agent:        connecting_to_agent.md"
  [[ "$ENABLE_KB" == true ]]    && info "  KB Admin Console:        frontend/README.md (login: admin@metronix.local / metronix)"
  [[ "$ENABLE_WEBUI" == true ]] && info "  Open WebUI:              docs/integrations/openwebui.md"
  info "  Ports & troubleshooting: install.md"
}

main() {
  print_banner
  parse_args "$@"
  cd "$REPO_ROOT"
  # Standalone agent-wiring: skip the stack build entirely.
  if [[ "$WIRE_HERMES" == true && "$ASSUME_YES" == true ]]; then
    [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found — run a full install first, or cd to the deployment dir."; exit 1; }
    wire_hermes
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
