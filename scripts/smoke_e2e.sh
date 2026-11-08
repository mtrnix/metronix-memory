#!/usr/bin/env bash
# End-to-end smoke test: an agent stores a fact over MCP, the core service is
# restarted, and the same agent recalls the fact. Exit 0 only on success.
#
# Uses METRONIX_AGENT_KEY / METRONIX_AGENT_ID from .env (written by
# scripts/provision_agent.sh); both can be overridden through the environment.
# The test record is deleted at the end.
#
# Usage: scripts/smoke_e2e.sh [--no-restart]
set -euo pipefail

# shellcheck source=scripts/lib/metronix.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/metronix.sh"

RESTART=true
READY_TIMEOUT_SECONDS="${SMOKE_READY_TIMEOUT:-300}"
RECALL_ATTEMPTS=6
RECALL_RETRY_SECONDS=5

[[ "${1:-}" == "--no-restart" ]] && RESTART=false

fail() { err "SMOKE TEST FAILED: $*"; exit 1; }

KEY="${METRONIX_AGENT_KEY:-$(env_get METRONIX_AGENT_KEY)}"
AGENT_ID="${METRONIX_AGENT_ID:-$(env_get METRONIX_AGENT_ID)}"
WORKSPACE_ID="${METRONIX_WORKSPACE_ID:-$(env_get DEFAULT_WORKSPACE_ID)}"
WORKSPACE_ID="${WORKSPACE_ID:-MTRNIX}"
[[ "$KEY" == mtk_* ]] || fail "no personal mtk_ key (run scripts/provision_agent.sh)"
[[ -n "$AGENT_ID" ]] || fail "no agent id (run scripts/provision_agent.sh)"

TOKEN="smoke-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
FACT="Metronix smoke test $TOKEN: the deploy window for project $TOKEN is Thursday 14:00 UTC."
SCOPE="\"agent_id\":\"$AGENT_ID\",\"workspace_id\":\"$WORKSPACE_ID\""

store_fact() {
  local resp e
  resp="$(mcp_call "$KEY" "$AGENT_ID" metronix_memory_store \
    "{$SCOPE,\"content\":$(json_str "$FACT"),\"tags\":[\"smoke-test\"]}")" \
    || fail "store request to $API_URL/mcp failed"
  e="$(mcp_error "$resp")"
  [[ -z "$e" ]] || fail "metronix_memory_store: $e"
  RECORD_ID="$(json_eval 'd["result"]["structuredContent"]["id"]' <<<"$resp")" \
    || fail "store returned no record id: ${resp:0:200}"
  ok "Stored fact $RECORD_ID as agent $AGENT_ID"
}

restart_core() {
  info "Restarting metronix-core ..."
  compose restart metronix-core >/dev/null || fail "docker compose restart metronix-core failed"
  wait_ready "$READY_TIMEOUT_SECONDS" || fail "API not ready after restart"
}

# Search is the recall path agents use; retry briefly in case indexing lags.
recall_fact() {
  local resp e found i
  for ((i = 1; i <= RECALL_ATTEMPTS; i++)); do
    resp="$(mcp_call "$KEY" "$AGENT_ID" metronix_memory_search \
      "{$SCOPE,\"query\":\"When is the deploy window for project $TOKEN?\",\"top_k\":5}")" \
      || fail "search request failed"
    e="$(mcp_error "$resp")"
    [[ -z "$e" ]] || fail "metronix_memory_search: $e"
    found="$(json_eval "any('$TOKEN' in (r.get('record') or {}).get('content', '') for r in d['result']['structuredContent'].get('results', []))" <<<"$resp")"
    if [[ "$found" == true ]]; then
      ok "Recalled the fact after restart (attempt $i)"
      return 0
    fi
    sleep "$RECALL_RETRY_SECONDS"
  done
  fail "fact $RECORD_ID not returned by metronix_memory_search after restart: ${resp:0:300}"
}

cleanup() {
  [[ -n "${RECORD_ID:-}" ]] || return 0
  local resp
  resp="$(mcp_call "$KEY" "$AGENT_ID" metronix_memory_delete "{$SCOPE,\"record_id\":\"$RECORD_ID\"}" || true)"
  if [[ -n "$resp" && -z "$(mcp_error "$resp")" ]]; then
    info "Deleted test record $RECORD_ID"
  else
    warn "Could not delete test record $RECORD_ID (tag smoke-test); remove it manually."
  fi
}

main() {
  info "Smoke test against $API_URL (agent $AGENT_ID, workspace $WORKSPACE_ID)"
  wait_ready "$READY_TIMEOUT_SECONDS" || fail "API not ready before the test"
  store_fact
  trap cleanup EXIT
  if [[ "$RESTART" == true ]]; then restart_core; fi
  recall_fact
  ok "SMOKE TEST PASSED"
}

main
