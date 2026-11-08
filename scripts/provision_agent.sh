#!/usr/bin/env bash
# Create (or reuse) a personal mtk_ key for one agent and write ready-to-paste
# MCP configs for Claude Desktop, Cursor and VS Code.
#
# Memory tools (metronix_memory_*) need a user principal; the shared
# METRONIX_MCP_API_KEY does not carry one and gets AUTH_REQUIRED (#540).
# So this script logs in as the seeded admin (AUTH_PASSWORD from .env), mints a
# key labelled with the agent id, verifies it with a real memory call, and keeps
# it in .env as METRONIX_AGENT_KEY. Re-runs reuse a key that still works.
#
# Usage: scripts/provision_agent.sh [--agent-id ID] [--out DIR]
set -euo pipefail

# shellcheck source=scripts/lib/metronix.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/metronix.sh"

ADMIN_EMAIL="admin@metronix.local"
AGENT_ID=""
OUT_DIR="$REPO_ROOT/client-configs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-id) AGENT_ID="${2:?--agent-id requires a value}"; shift 2 ;;
    --out)      OUT_DIR="${2:?--out requires a value}"; shift 2 ;;
    -h|--help)  sed -n 2,12p "$0"; exit 0 ;;
    *) err "Unknown option: $1"; exit 2 ;;
  esac
done

new_agent_id() { od -An -N16 -tx1 /dev/urandom | tr -d ' \n'; }

resolve_agent_id() {
  AGENT_ID="${AGENT_ID:-$(env_get METRONIX_AGENT_ID)}"
  AGENT_ID="${AGENT_ID:-$(new_agent_id)}"
  if [[ ! "$AGENT_ID" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
    err "Invalid agent id '$AGENT_ID' (allowed: letters, digits, . _ -, max 128)."
    exit 2
  fi
  env_set METRONIX_AGENT_ID "$AGENT_ID"
}

# True when KEY can actually use the memory tools for AGENT_ID.
key_works() {
  local key="$1" resp
  [[ "$key" == mtk_* ]] || return 1
  resp="$(mcp_call "$key" "$AGENT_ID" metronix_memory_list \
    "{\"agent_id\":\"$AGENT_ID\",\"workspace_id\":\"$WORKSPACE_ID\",\"limit\":1}")" || return 1
  [[ -z "$(mcp_error "$resp")" ]]
}

admin_login() {
  local password resp
  password="$(env_get AUTH_PASSWORD)"
  if [[ -z "$password" ]]; then
    err "AUTH_PASSWORD is empty in $ENV_FILE, so no admin account exists to issue keys."
    err "Fresh installs get one from install.sh. For an existing install, set it to your"
    err "admin password in .env (it only seeds an empty users table)."
    exit 1
  fi
  resp="$(curl -sS --max-time 30 -X POST "$API_URL/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":$(json_str "$password")}")" \
    || { err "Login request to $API_URL failed."; exit 1; }
  ADMIN_JWT="$(json_eval 'd.get("token") or ""' <<<"$resp")"
  ADMIN_USER_ID="$(json_eval 'd.get("user_id") or ""' <<<"$resp")"
  if [[ -z "$ADMIN_JWT" || -z "$ADMIN_USER_ID" ]]; then
    err "Admin login failed: ${resp:0:200}"
    err "AUTH_PASSWORD in .env must match the admin password set on first start."
    exit 1
  fi
}

mint_key() {
  local resp
  resp="$(curl -sS --max-time 30 -X POST "$API_URL/api/v1/users/$ADMIN_USER_ID/api-keys" \
    -H "Authorization: Bearer $ADMIN_JWT" -H 'Content-Type: application/json' \
    -d "{\"label\":\"agent:$AGENT_ID\"}")" || { err "Key creation request failed."; exit 1; }
  AGENT_KEY="$(json_eval 'd.get("raw_key") or ""' <<<"$resp")"
  [[ "$AGENT_KEY" == mtk_* ]] || { err "Key creation failed: ${resp:0:200}"; exit 1; }
}

ensure_agent_key() {
  AGENT_KEY="$(env_get METRONIX_AGENT_KEY)"
  if [[ -n "$AGENT_KEY" ]] && key_works "$AGENT_KEY"; then
    ok "Reusing METRONIX_AGENT_KEY from .env (verified with metronix_memory_list)"
    return 0
  fi
  [[ -n "$AGENT_KEY" ]] && warn "METRONIX_AGENT_KEY in .env no longer works; issuing a new one."
  admin_login
  mint_key
  key_works "$AGENT_KEY" || { err "New key was rejected by metronix_memory_list."; exit 1; }
  env_set METRONIX_AGENT_KEY "$AGENT_KEY"
  ok "Issued a personal key for agent '$AGENT_ID' and saved it as METRONIX_AGENT_KEY in .env"
}

write_configs() {
  local mcp_url="$API_URL/mcp"
  mkdir -p "$OUT_DIR"
  chmod 700 "$OUT_DIR"
  umask 077
  cat > "$OUT_DIR/claude_desktop_config.json" <<EOF
{
  "mcpServers": {
    "metronix": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.14.3", "$mcp_url",
               "--header", "Authorization:\${METRONIX_AUTH_HEADER}",
               "--header", "X-Agent-Id:$AGENT_ID"],
      "env": { "METRONIX_AUTH_HEADER": "Bearer $AGENT_KEY" }
    }
  }
}
EOF
  cat > "$OUT_DIR/cursor_mcp.json" <<EOF
{
  "mcpServers": {
    "metronix": {
      "url": "$mcp_url",
      "headers": { "Authorization": "Bearer $AGENT_KEY", "X-Agent-Id": "$AGENT_ID" }
    }
  }
}
EOF
  cat > "$OUT_DIR/vscode_mcp.json" <<EOF
{
  "servers": {
    "metronix": {
      "type": "http",
      "url": "$mcp_url",
      "headers": { "Authorization": "Bearer $AGENT_KEY", "X-Agent-Id": "$AGENT_ID" }
    }
  }
}
EOF
}

print_configs() {
  info ""
  info "================ MCP client configs (contain your key; keep private) ================"
  info "Claude Desktop -> claude_desktop_config.json (Settings > Developer > Edit Config):"
  cat "$OUT_DIR/claude_desktop_config.json"
  info ""
  info "Cursor -> ~/.cursor/mcp.json:"
  cat "$OUT_DIR/cursor_mcp.json"
  info ""
  info "VS Code -> .vscode/mcp.json:"
  cat "$OUT_DIR/vscode_mcp.json"
  info ""
  info "Copies: $OUT_DIR/{claude_desktop_config.json,cursor_mcp.json,vscode_mcp.json}"
  info "Tool calls must pass agent_id=\"$AGENT_ID\" and workspace_id=\"$WORKSPACE_ID\"."
}

main() {
  [[ -f "$ENV_FILE" ]] || { err "$ENV_FILE not found. Run ./install.sh -y first."; exit 1; }
  WORKSPACE_ID="$(env_get DEFAULT_WORKSPACE_ID)"; WORKSPACE_ID="${WORKSPACE_ID:-MTRNIX}"
  resolve_agent_id
  ensure_agent_key
  write_configs
  print_configs
}

main "$@"
