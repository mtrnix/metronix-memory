# shellcheck shell=bash
# Shared helpers for scripts/quickstart.sh, scripts/provision_agent.sh and
# scripts/smoke_e2e.sh. Source it; do not execute it.
#
# JSON is parsed with the Python inside the API container, so the host needs
# only bash, curl and docker (no jq / python on a fresh VM).

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
API_URL="${METRONIX_API_URL:-http://localhost:${API_PORT:-8000}}"
API_CONTAINER="${METRONIX_API_CONTAINER:-metronix-full-api}"
OLLAMA_CONTAINER="${METRONIX_OLLAMA_CONTAINER:-metronix-full-ollama}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.yml}"
READY_POLL_SECONDS=5

if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_RST=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_RST=""
fi
info() { printf '%s\n' "$*"; }
ok()   { printf '%s\xe2\x9c\x93%s %s\n' "$C_OK" "$C_RST" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_RST" "$*"; }
err()  { printf '%s\xe2\x9c\x97%s %s\n' "$C_ERR" "$C_RST" "$*" >&2; }

# Read KEY from .env (empty if absent).
env_get() {
  [[ -f "$ENV_FILE" ]] || return 0
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

# Upsert KEY=VALUE in .env, literally (same semantics as install.sh set_env).
env_set() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    awk -v k="$key" -v v="$val" '$0 ~ "^" k "=" { print k "=" v; next } { print }' \
      "$ENV_FILE" > "$tmp"
    cat "$tmp" > "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
  rm -f "$tmp"
}

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# Secrets are printed in full for the person installing; CI sets
# METRONIX_MASK_SECRETS=1 so public logs only show a prefix and suffix.
mask() { local v="$1"; if (( ${#v} > 12 )); then printf '%s…%s' "${v:0:4}" "${v: -4}"; else printf '****'; fi; }
reveal() { if [[ "${METRONIX_MASK_SECRETS:-0}" == 1 ]]; then mask "$1"; else printf '%s' "$1"; fi; }

# Evaluate a Python expression over the JSON document on stdin, bound to `d`.
# Prints the result (strings bare, everything else as JSON). Exit 1 on error.
json_eval() {
  docker exec -i "$API_CONTAINER" python -c '
import json, sys
d = json.load(sys.stdin)
v = eval(sys.argv[1], {"d": d, "json": json})
print(v if isinstance(v, str) else json.dumps(v))
' "$1"
}

# JSON-encode a string (for safe embedding in a request body).
json_str() {
  printf '%s' "$1" | docker exec -i "$API_CONTAINER" python -c \
    'import json, sys; print(json.dumps(sys.stdin.read()))'
}

# mcp_call KEY AGENT_ID TOOL ARGS_JSON -> prints the JSON-RPC response object.
# Streamable-HTTP answers as SSE; keep only the data: payload.
mcp_call() {
  local key="$1" agent="$2" tool="$3" args="$4" body raw
  body="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$tool\",\"arguments\":$args}}"
  raw="$(curl -sS --max-time 60 -X POST "$API_URL/mcp" \
    -H "Authorization: Bearer $key" -H "X-Agent-Id: $agent" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d "$body")" || return 1
  if grep -q '^data: ' <<<"$raw"; then
    sed -n 's/^data: //p' <<<"$raw" | tail -1
  else
    printf '%s\n' "$raw"
  fi
}

# The error (if any) carried by an MCP tool response; empty when the call succeeded.
mcp_error() {
  json_eval '(d.get("error") or {}).get("message") or ((d.get("result") or {}).get("structuredContent") or {}).get("error") or ("tool error: " + json.dumps(d["result"].get("content")) if (d.get("result") or {}).get("isError") else "")' \
    <<<"$1" 2>/dev/null || echo "unparseable MCP response: ${1:0:200}"
}

_ollama_progress() {
  # Ollama draws a terminal progress bar; drop its ANSI escape sequences.
  docker logs --tail 5 "$OLLAMA_CONTAINER" 2>&1 | tr '\r' '\n' \
    | sed -E $'s/\x1b\\[[0-9;?]*[A-Za-z]//g' \
    | grep -E 'pulling|verifying|success' | tail -1 | cut -c1-100
}

# wait_ready TIMEOUT_SECONDS: poll /ready until HTTP 200, printing each change in
# per-service status and Ollama model-pull progress. Returns 1 on timeout with
# the last /ready body and the tail of the API log.
wait_ready() {
  local timeout="$1" start now body code last="" progress last_progress=""
  start="$(date +%s)"
  info "Waiting for $API_URL/ready (timeout ${timeout}s) ..."
  while :; do
    body="$(curl -sS --max-time 10 -w $'\n%{http_code}' "$API_URL/ready" 2>/dev/null || true)"
    code="${body##*$'\n'}"; body="${body%$'\n'*}"
    now="$(date +%s)"
    if [[ "$code" == 200 ]]; then
      ok "Ready after $((now - start))s: $body"
      return 0
    fi
    if [[ "$body" != "$last" ]]; then
      info "  [$((now - start))s] /ready -> HTTP ${code:-000} ${body:-<no response yet>}"
      last="$body"
    fi
    progress="$(_ollama_progress)"
    if [[ -n "$progress" && "$progress" != "$last_progress" ]]; then
      info "  [$((now - start))s] ollama: $progress"
      last_progress="$progress"
    fi
    if (( now - start >= timeout )); then
      err "Not ready after ${timeout}s. Last /ready: HTTP ${code:-000} ${body:-<none>}"
      err "Last API log lines:"
      docker logs --tail 30 "$API_CONTAINER" >&2 2>&1 || true
      return 1
    fi
    sleep "$READY_POLL_SECONDS"
  done
}
