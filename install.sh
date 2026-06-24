#!/usr/bin/env bash
# Metronix Core installer — builds and starts the full stack from source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.full.yml"
ENV_FILE=".env"
EXAMPLE_FILE=".env.example"
API_PORT=8000
WEBUI_PORT=3080

PROVIDER=""
API_KEY=""
OLLAMA_HOST=""
CUSTOM_URL=""
CUSTOM_MODEL=""
ENABLE_WEBUI=false
ASSUME_YES=false
RECONFIGURE=false
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

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Builds and starts Metronix Core from source via docker-compose.full.yml.

Options:
  --provider <name>    LLM provider: ollama (default) | custom
  --api-key <key>      API key for the custom endpoint (provider=custom)
  --ollama-host <url>  External Ollama host (provider=ollama; blank uses bundled Ollama)
  --custom-url <url>   Endpoint URL, e.g. https://api.deepseek.com/v1 (provider=custom)
  --custom-model <m>   Model name the endpoint serves, e.g. deepseek-chat (provider=custom)
  --openwebui          Enable the Open WebUI chat interface (:3080)
  -y, --yes            Non-interactive: use defaults/flags, never prompt
  --reconfigure        Re-run configuration even if .env already exists
  -h, --help           Show this help

Examples:
  ./install.sh
  ./install.sh --provider custom --custom-url https://api.deepseek.com/v1 --api-key sk-... --custom-model deepseek-chat --openwebui
  ./install.sh --provider ollama --yes
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --provider)    [[ $# -ge 2 ]] || { err "--provider requires a value"; exit 2; }; PROVIDER="$2"; shift 2 ;;
      --api-key)     [[ $# -ge 2 ]] || { err "--api-key requires a value"; exit 2; }; API_KEY="$2"; shift 2 ;;
      --ollama-host) [[ $# -ge 2 ]] || { err "--ollama-host requires a value"; exit 2; }; OLLAMA_HOST="$2"; shift 2 ;;
      --custom-url)   [[ $# -ge 2 ]] || { err "--custom-url requires a value"; exit 2; }; CUSTOM_URL="$2"; shift 2 ;;
      --custom-model) [[ $# -ge 2 ]] || { err "--custom-model requires a value"; exit 2; }; CUSTOM_MODEL="$2"; shift 2 ;;
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
  cp "$EXAMPLE_FILE" "$ENV_FILE"

  if [[ -z "$PROVIDER" ]]; then
    if [[ "$ASSUME_YES" == true ]]; then
      PROVIDER="ollama"
    else
      info "LLM provider:"
      info "  1) ollama     (bundled, no API key — default)"
      info "  2) custom     (any OpenAI-compatible endpoint — DeepSeek, OpenRouter, vLLM, ...)"
      read -rp "Choose [1-2] (1): " ans
      case "${ans:-1}" in
        1|"") PROVIDER=ollama ;;
        2)    PROVIDER=custom ;;
        *)    err "Invalid choice: $ans"; exit 1 ;;
      esac
    fi
  fi
  case "$PROVIDER" in
    ollama|custom) ;;
    *)
      err "Unsupported provider: $PROVIDER. Supported: ollama | custom."
      err "Use --provider custom --custom-url URL --custom-model MODEL for external endpoints."
      exit 1
      ;;
  esac
  set_env LLM_PROVIDER "$PROVIDER"

  case "$PROVIDER" in
    custom)
      if [[ -z "$API_KEY" && "$ASSUME_YES" == false ]]; then
        read -rsp "API key for the endpoint: " API_KEY; echo
      fi
      [[ -n "$API_KEY" ]] || { err "custom provider requires an API key (--api-key)"; exit 1; }
      set_env LLM_PROVIDER_API_KEY "$API_KEY"
      if [[ -z "$CUSTOM_URL" && "$ASSUME_YES" == false ]]; then
        read -rp "Endpoint URL (https://host/v1, e.g. https://api.deepseek.com/v1): " CUSTOM_URL
      fi
      [[ -n "$CUSTOM_URL" ]] || { err "custom provider requires --custom-url"; exit 1; }
      set_env LLM_PROVIDER_URL "$CUSTOM_URL"
      if [[ -z "$CUSTOM_MODEL" && "$ASSUME_YES" == false ]]; then
        read -rp "Model the endpoint serves (e.g. deepseek-chat): " CUSTOM_MODEL
      fi
      [[ -n "$CUSTOM_MODEL" ]] || { err "custom provider requires a model (--custom-model)"; exit 1; }
      set_env LLM_PROVIDER_MODEL "$CUSTOM_MODEL"
      ;;
    ollama)
      if [[ -z "$OLLAMA_HOST" && "$ASSUME_YES" == false ]]; then
        read -rp "External Ollama host URL (blank = use bundled Ollama): " OLLAMA_HOST
      fi
      [[ -n "$OLLAMA_HOST" ]] && set_env OLLAMA_HOST "$OLLAMA_HOST"
      ;;
  esac

  if [[ "$ENABLE_WEBUI" == false && "$ASSUME_YES" == false ]]; then
    read -rp "Enable Open WebUI chat interface (:$WEBUI_PORT)? [y/N]: " ans
    [[ "$ans" =~ ^[Yy] ]] && ENABLE_WEBUI=true
  fi

  set_env POSTGRES_PASSWORD "$(resolve_secret POSTGRES_PASSWORD "$prev_pg" "$(gen_secret)")"
  set_env NEO4J_PASSWORD "$(resolve_secret NEO4J_PASSWORD "$prev_neo" "$(gen_secret)")"
  set_env METRONIX_MCP_API_KEY "$(resolve_secret METRONIX_MCP_API_KEY "$prev_mcp" "$(gen_secret)")"
  set_env FERNET_KEY "$(resolve_secret FERNET_KEY "$prev_fernet" "$(gen_fernet)")"

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
