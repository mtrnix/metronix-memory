#!/usr/bin/env bash
# One command from a clean machine to a verified agent memory:
#   1. install.sh -y: .env with every secret (one generator), images, stack up
#      (Alembic migrations run on API startup)
#   2. wait for /ready: schema at head, Qdrant, Neo4j, embedding model pulled
#   3. provision_agent.sh: per-agent mtk_ key + Claude Desktop / Cursor / VS Code configs
#   4. smoke_e2e.sh: store a fact, restart the core service, recall it
#   5. print the final credentials and where they live
# Exits non-zero at the first failing step.
#
# Usage: scripts/quickstart.sh [--agent-id ID] [-- extra install.sh options]
# Env:   METRONIX_READY_TIMEOUT (seconds, default 1200)
set -euo pipefail

# shellcheck source=scripts/lib/metronix.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/metronix.sh"

READY_TIMEOUT_SECONDS="${METRONIX_READY_TIMEOUT:-1200}"
PROVISION_ARGS=()
INSTALL_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-id) PROVISION_ARGS+=(--agent-id "${2:?--agent-id requires a value}"); shift 2 ;;
    --) shift; INSTALL_ARGS=("$@"); break ;;
    -h|--help) sed -n 2,13p "$0"; exit 0 ;;
    *) err "Unknown option: $1 (install.sh options go after --)"; exit 2 ;;
  esac
done

START_TS="$(date +%s)"
step() { info ""; info "==> [$(( $(date +%s) - START_TS ))s] $*"; }
on_exit() {
  local rc=$?
  (( rc == 0 )) && return
  err "Quickstart failed (exit $rc) after $(( $(date +%s) - START_TS ))s."
  err "Diagnose: docker compose -f $COMPOSE_FILE ps; docker compose -f $COMPOSE_FILE logs --tail 100 metronix-core"
}
trap on_exit EXIT

mask() { local v="$1"; (( ${#v} > 8 )) && printf '%s…%s' "${v:0:4}" "${v: -4}" || printf '****'; }

print_summary() {
  info ""
  info "================================ Credentials ================================"
  info "All generated values live in one file: $ENV_FILE (chmod 600)."
  info "  Admin login       : admin@metronix.local / AUTH_PASSWORD = $(env_get AUTH_PASSWORD)"
  info "  Agent id          : METRONIX_AGENT_ID = $(env_get METRONIX_AGENT_ID)"
  info "  Agent key (mtk_)  : METRONIX_AGENT_KEY = $(env_get METRONIX_AGENT_KEY)"
  info "  Workspace         : $(env_get DEFAULT_WORKSPACE_ID)"
  info "  Shared /mcp key   : METRONIX_MCP_API_KEY = $(mask "$(env_get METRONIX_MCP_API_KEY)")"
  info "                      (opens /mcp only; memory tools need the agent key above)"
  info "  Internal DB/secret: POSTGRES_PASSWORD, NEO4J_PASSWORD, FERNET_KEY, METRONIX_SECRET_KEY"
  info ""
  info "API: $API_URL   MCP: $API_URL/mcp   Total time: $(( $(date +%s) - START_TS ))s"
}

main() {
  command -v curl >/dev/null 2>&1 || { err "curl is required."; exit 1; }

  step "Install and start the stack (image pulls and build show progress below)"
  (cd "$REPO_ROOT" && ./install.sh -y --no-connect ${INSTALL_ARGS[@]+"${INSTALL_ARGS[@]}"})
  chmod 600 "$ENV_FILE"

  step "Wait for readiness (migrations at head, stores up, embedding model pulled)"
  wait_ready "$READY_TIMEOUT_SECONDS"

  step "Issue a per-agent key and write client configs"
  "$REPO_ROOT/scripts/provision_agent.sh" ${PROVISION_ARGS[@]+"${PROVISION_ARGS[@]}"}

  step "End-to-end smoke test"
  "$REPO_ROOT/scripts/smoke_e2e.sh"

  print_summary
}

main
