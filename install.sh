#!/usr/bin/env bash
# Metronix Core installer — builds and starts the full stack from source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.full.yml"
ENV_FILE=".env"
EXAMPLE_FILE=".env.example"
API_PORT=8000
WEBUI_PORT=3080

MODE=""              # "memory" | "answers" (how Metronix is used)
CHAT_URL=""          # OpenAI-compatible chat-model endpoint (answers mode)
CHAT_MODEL=""        # model name the endpoint serves (answers mode)
CHAT_API_KEY=""      # bearer token for the endpoint (optional; blank = no auth)
ENABLE_WEBUI=false
ASSUME_YES=false
RECONFIGURE=false
WIRE_HERMES=false    # run the Hermes wiring step (and, with -y, apply without prompt)
AGENT_ID=""          # override the generated X-Agent-Id (Hermes wiring)
METRONIX_URL=""      # override the MCP URL written into the agent config
COMPOSE=()

if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_RST=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_RST=""
fi
info() { printf '%s\n' "$*"; }
ok()   { printf '%s\xe2\x9c\x93%s %s\n' "$C_OK" "$C_RST" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_RST" "$*"; }
err()  { printf '%s\xe2\x9c\x97%s %s\n' "$C_ERR" "$C_RST" "$*" >&2; }

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

Builds and starts Metronix Core from source via docker-compose.full.yml.

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
  --wire-hermes            Connect the Hermes agent to Metronix (edit ~/.hermes
                           config); with -y, apply without prompting. Also offered
                           interactively at the end of a normal install.
  --agent-id <id>          Override the generated agent id (X-Agent-Id)
  --metronix-url <url>     MCP URL written into the agent config
                           (default http://localhost:8000/mcp)
  -y, --yes                Non-interactive: use defaults/flags, never prompt
  --reconfigure            Re-run configuration even if .env already exists
  -h, --help               Show this help

If --chat-url is given, --mode defaults to "answers"; otherwise "memory".

Examples:
  ./install.sh                                    # memory store for an agent (default)
  ./install.sh --mode answers \
      --chat-url https://api.deepseek.com/v1 --chat-model deepseek-chat \
      --chat-api-key sk-...
  ./install.sh --chat-url http://host.docker.internal:11434/v1 \
      --chat-model llama3.1:8b -y                 # local Ollama, no token
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
      -y|--yes)      ASSUME_YES=true; shift ;;
      --reconfigure) RECONFIGURE=true; shift ;;
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

configure() {
  if [[ -f "$ENV_FILE" && "$RECONFIGURE" == false ]]; then
    ok ".env already exists — reusing it (use --reconfigure to redo)"
    return 0
  fi

  if [[ "$ASSUME_YES" == false && ! -t 0 ]]; then
    err "No terminal for interactive prompts. Re-run with -y/--yes (and pass --provider plus --custom-url/--custom-model/--api-key when using custom), or run from an interactive shell."
    exit 2
  fi

  # Preserve secrets across --reconfigure (don't rotate live DB passwords).
  local prev_pg prev_neo prev_mcp prev_fernet
  prev_pg="$(get_env POSTGRES_PASSWORD)"
  prev_neo="$(get_env NEO4J_PASSWORD)"
  prev_mcp="$(get_env METRONIX_MCP_API_KEY)"
  prev_fernet="$(get_env FERNET_KEY)"

  [[ -f "$EXAMPLE_FILE" ]] || { err "$EXAMPLE_FILE not found in $(pwd)"; exit 1; }

  # Stage the new config in a temp file and promote it to $ENV_FILE only after
  # everything validates. A partial or aborted run (e.g. a blank required field)
  # must never leave a half-written .env behind — otherwise the next run sees an
  # existing .env, skips all prompts, and launches with a broken config.
  local final_env="$ENV_FILE"
  ENV_FILE="$(mktemp "${final_env}.XXXXXX")"
  trap 'rm -f "$ENV_FILE"' EXIT
  cp "$EXAMPLE_FILE" "$ENV_FILE"

  info "Vector embeddings run locally on the bundled Ollama (model: nomic-embed-text),"
  info "set up automatically. The choice below is only about answer generation (chat)."
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
    set_env OLLAMA_CHAT_MODEL ""   # bundled Ollama stays embeddings-only
    ok "Answer generation -> $CHAT_URL (model: $CHAT_MODEL)"
  else
    # Memory store: the connected agent does the answering. No chat model is
    # configured and the bundled Ollama never pulls one (embeddings only).
    set_env LLM_PROVIDER ollama
    set_env OLLAMA_CHAT_MODEL ""
    ok "Memory-store mode — no answer-generation model configured."
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

  # Resolve secrets into plain variables first. A failed generator inside the
  # nested $(...) of a set_env call does NOT trip `set -e` — it just yields an
  # empty string, and set_env would happily write "KEY=" and return 0. So we
  # compute the values, then explicitly refuse to proceed if any came out blank
  # (e.g. neither openssl nor /dev/urandom produced output).
  local val_pg val_neo val_mcp val_fernet
  val_pg="$(resolve_secret POSTGRES_PASSWORD "$prev_pg" "$(gen_secret)")"
  val_neo="$(resolve_secret NEO4J_PASSWORD "$prev_neo" "$(gen_secret)")"
  val_mcp="$(resolve_secret METRONIX_MCP_API_KEY "$prev_mcp" "$(gen_secret)")"
  val_fernet="$(resolve_secret FERNET_KEY "$prev_fernet" "$(gen_fernet)")"

  local _pair
  for _pair in "POSTGRES_PASSWORD:$val_pg" "NEO4J_PASSWORD:$val_neo" \
               "METRONIX_MCP_API_KEY:$val_mcp" "FERNET_KEY:$val_fernet"; do
    if [[ -z "${_pair#*:}" ]]; then
      err "Could not generate a value for ${_pair%%:*} (need openssl or a readable /dev/urandom). Aborting before launch."
      exit 1
    fi
  done

  set_env POSTGRES_PASSWORD "$val_pg"
  set_env NEO4J_PASSWORD "$val_neo"
  set_env METRONIX_MCP_API_KEY "$val_mcp"
  set_env FERNET_KEY "$val_fernet"

  # Everything validated — promote the staged config atomically and disarm the
  # cleanup trap so the real .env survives.
  mv "$ENV_FILE" "$final_env"
  trap - EXIT
  ENV_FILE="$final_env"
  ok "Wrote $ENV_FILE"
}

launch() {
  local args=(-f "$COMPOSE_FILE")
  [[ "$ENABLE_WEBUI" == true ]] && args+=(--profile openwebui)
  args+=(up -d --build)
  info "Building and starting the stack (first run can take 10-15 min)..."
  "${COMPOSE[@]}" "${args[@]}"
}

wait_health() {
  command -v curl >/dev/null 2>&1 || { warn "curl not found — skipping health check."; return 0; }
  info "Waiting for the API on :$API_PORT ..."
  local _i
  for _i in $(seq 1 60); do
    if curl -fsS "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
      ok "API is healthy"
      return 0
    fi
    sleep 5
  done
  warn "API did not report healthy within ~5 min. It may still be building."
  warn "  Check logs: ${COMPOSE[*]} -f $COMPOSE_FILE logs -f metronix-core"
  return 0
}

print_links() {
  info ""
  ok "Metronix Core is up."
  info "  API:          http://localhost:$API_PORT"
  info "  MCP endpoint: http://localhost:$API_PORT/mcp"
  [[ "$ENABLE_WEBUI" == true ]] && info "  Open WebUI:   http://localhost:$WEBUI_PORT"
  info ""
  info "Manage the stack:"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE ps        # status"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE logs -f   # logs"
  info "  ${COMPOSE[*]} -f $COMPOSE_FILE down      # stop"
}

main() {
  parse_args "$@"
  cd "$REPO_ROOT"
  check_prereqs
  configure
  launch
  wait_health
  print_links
}

# Allow sourcing for tests without running main.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
