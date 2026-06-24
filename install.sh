#!/usr/bin/env bash
# Metronix Core installer — builds and starts the full stack from source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034  # globals consumed by later tasks sourcing this file
COMPOSE_FILE="docker-compose.full.yml"
# shellcheck disable=SC2034
ENV_FILE=".env"
# shellcheck disable=SC2034
EXAMPLE_FILE=".env.example"
# shellcheck disable=SC2034
API_PORT=8000
# shellcheck disable=SC2034
WEBUI_PORT=3080

# Flag state / defaults
# shellcheck disable=SC2034  # set by parse_args, consumed by configure/launch tasks
PROVIDER=""
# shellcheck disable=SC2034
API_KEY=""
# shellcheck disable=SC2034
OLLAMA_HOST=""
# shellcheck disable=SC2034
CUSTOM_URL=""
# shellcheck disable=SC2034
ENABLE_WEBUI=false
# shellcheck disable=SC2034
ASSUME_YES=false
# shellcheck disable=SC2034
RECONFIGURE=false
COMPOSE=()

# Colors only on a TTY
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
  --provider <name>    LLM provider: ollama (default) | deepseek | openrouter | custom
  --api-key <key>      API key (deepseek / openrouter / custom)
  --ollama-host <url>  External Ollama host (provider=ollama; blank uses bundled Ollama)
  --custom-url <url>   Endpoint URL (provider=custom)
  --openwebui          Enable the Open WebUI chat interface (:3080)
  -y, --yes            Non-interactive: use defaults/flags, never prompt
  --reconfigure        Re-run configuration even if .env already exists
  -h, --help           Show this help

Examples:
  ./install.sh
  ./install.sh --provider deepseek --api-key sk-... --openwebui
  ./install.sh --provider ollama --yes
EOF
}

parse_args() {
  # shellcheck disable=SC2034  # globals consumed by later tasks sourcing this file
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --provider)    PROVIDER="${2:-}"; shift 2 ;;
      --api-key)     API_KEY="${2:-}"; shift 2 ;;
      --ollama-host) OLLAMA_HOST="${2:-}"; shift 2 ;;
      --custom-url)  CUSTOM_URL="${2:-}"; shift 2 ;;
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

main() {
  parse_args "$@"
  cd "$REPO_ROOT"
  check_prereqs
}

# Allow sourcing for tests without running main.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
