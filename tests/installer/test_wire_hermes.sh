#!/usr/bin/env bash
# Tests for the Hermes wiring in install.sh. Sandboxed; no docker, no real ~/.hermes.
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

echo "Task1: flags parse into globals"
out="$(bash -c "source '$INSTALL'; parse_args --wire-hermes --agent-id abc123 --metronix-url http://x:8000/mcp; echo \"\$WIRE_HERMES|\$AGENT_ID|\$METRONIX_URL\"")"
chk "flags parsed" "$out" "true|abc123|http://x:8000/mcp"
chk "usage lists --wire-hermes" "$(bash -c "source '$INSTALL'; usage" | grep -c -- '--wire-hermes')" "1"

echo "Task2: agent id resolution"
gid="$(bash -c "source '$INSTALL'; gen_agent_id")"
chk "gen_agent_id is 32 hex" "$(printf '%s' "$gid" | grep -cE '^[0-9a-f]{32}$')" "1"
d="$(mktemp -d)"; printf 'mcp_servers:\n  metronix:\n    headers:\n      X-Agent-Id: deadbeefdeadbeefdeadbeefdeadbeef\n' > "$d/config.yaml"
r="$(bash -c "source '$INSTALL'; AGENT_ID=''; resolve_agent_id '$d/config.yaml'")"
chk "reuses existing id" "$r" "deadbeefdeadbeefdeadbeefdeadbeef"
r2="$(bash -c "source '$INSTALL'; AGENT_ID='override999'; resolve_agent_id '$d/config.yaml'")"
chk "flag overrides reuse" "$r2" "override999"
r3="$(bash -c "source '$INSTALL'; AGENT_ID=''; resolve_agent_id '$d/none.yaml'")"
chk "generates when absent" "$(printf '%s' "$r3" | grep -cE '^[0-9a-f]{32}$')" "1"

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
