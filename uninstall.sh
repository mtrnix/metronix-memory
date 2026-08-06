#!/usr/bin/env bash
# Safely stop and remove a local Metronix deployment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOVE_VOLUMES=false
PURGE=false

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [options]

Stops and removes the Metronix Docker stack, including optional services such
as the Metronix Admin Console (metronix-memory-frontend), while preserving
stored data by default.

Options:
  --volumes  Delete named Docker volumes and all stored Metronix data.
  --purge    Also remove generated local files and Metronix agent wiring.
  -h, --help Show this help.

Examples:
  ./uninstall.sh
  ./uninstall.sh --volumes
  ./uninstall.sh --volumes --purge
EOF
}

err() { printf 'Error: %s\n' "$*" >&2; }
info() { printf '%s\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }

remove_marked_block() {
  local file="$1" tmp has_start=false has_end=false
  [[ -f "$file" ]] || return 0
  grep -qFx -- '--- metronix-config ---' "$file" && has_start=true
  grep -qFx -- '--- end metronix-config ---' "$file" && has_end=true
  if [[ "$has_start" == false && "$has_end" == false ]]; then
    return 0
  fi
  if [[ "$has_start" == false || "$has_end" == false ]]; then
    warn "Cannot safely remove an incomplete Metronix marker block in $file; review it manually."
    return 0
  fi
  if [[ ! -w "$file" ]]; then
    warn "Cannot update $file; remove its Metronix marker block manually."
    return 0
  fi
  tmp="$(mktemp "${file}.metronix-uninstall.XXXXXX")"
  awk '
    /^--- metronix-config ---$/ { skip=1; next }
    skip && /^--- end metronix-config ---$/ { skip=0; next }
    !skip { print }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

remove_hermes_server() {
  local file="$1" tmp
  [[ -f "$file" ]] || return 0
  if [[ ! -w "$file" ]]; then
    warn "Cannot update $file; remove mcp_servers.metronix manually."
    return 0
  fi
  tmp="$(mktemp "${file}.metronix-uninstall.XXXXXX")"
  awk '
    /^mcp_servers:[[:space:]]*$/ { in_mcp=1 }
    in_mcp && /^  metronix:[[:space:]]*$/ { skip=1; next }
    skip {
      if ($0 !~ /^ / || $0 ~ /^  [^[:space:]]/) { skip=0 }
      else { next }
    }
    { print }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

remove_codex_server() {
  local file="$1" tmp
  [[ -f "$file" ]] || return 0
  if [[ ! -w "$file" ]]; then
    warn "Cannot update $file; remove [mcp_servers.metronix] manually."
    return 0
  fi
  tmp="$(mktemp "${file}.metronix-uninstall.XXXXXX")"
  awk '
    /^\[mcp_servers\.metronix\]$/ { skip=1; next }
    skip && /^\[/ { skip=0 }
    !skip { print }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

purge_agent_wiring() {
  info 'Removing Metronix agent wiring.'
  remove_hermes_server "$HOME/.hermes/config.yaml"
  remove_marked_block "$HOME/.hermes/SOUL.md"
  remove_codex_server "$HOME/.codex/config.toml"
  remove_codex_server "$SCRIPT_DIR/.codex/config.toml"
  remove_marked_block "$HOME/.claude/CLAUDE.md"
  remove_marked_block "$SCRIPT_DIR/CLAUDE.md"
  remove_marked_block "$HOME/.codex/AGENTS.md"
  remove_marked_block "$SCRIPT_DIR/AGENTS.md"
  remove_marked_block "$HOME/.openclaw/workspace/SOUL.md"

  if command -v claude >/dev/null 2>&1; then
    claude mcp remove metronix >/dev/null 2>&1 || warn 'Could not remove the Claude Code Metronix MCP entry automatically.'
  else
    warn 'Claude Code CLI is unavailable; remove mcpServers.metronix from ~/.claude.json manually.'
  fi
  if command -v openclaw >/dev/null 2>&1; then
    openclaw mcp unset metronix >/dev/null 2>&1 || warn 'Could not remove the OpenClaw Metronix MCP entry automatically.'
  else
    warn 'OpenClaw CLI is unavailable; remove the metronix entry from ~/.openclaw/openclaw.json manually.'
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --volumes) REMOVE_VOLUMES=true ;;
    --purge) PURGE=true ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown option: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

command -v docker >/dev/null 2>&1 || { err 'Docker is required.'; exit 1; }
docker compose version >/dev/null 2>&1 || { err 'Docker Compose v2 is required.'; exit 1; }

compose=(docker compose --profile admin --profile openwebui --profile benchmarker down)
if [[ "$REMOVE_VOLUMES" == true ]]; then
  warn 'Deleting named Docker volumes permanently removes all stored Metronix data.'
  compose+=(-v)
fi

info 'Stopping and removing the Metronix Docker stack.'
( cd "$SCRIPT_DIR" && "${compose[@]}" )

if [[ "$PURGE" == true ]]; then
  warn 'Removing generated local files and Metronix agent wiring.'
  rm -f "$SCRIPT_DIR/.env"
  rm -rf "$SCRIPT_DIR/metronix-hermes-setup" "$SCRIPT_DIR/metronix-claude-code-setup" \
    "$SCRIPT_DIR/metronix-codex-setup" "$SCRIPT_DIR/metronix-openclaw-setup" \
    "$SCRIPT_DIR/metronix-agent-setup"
  purge_agent_wiring
fi

info 'Metronix uninstall complete.'
