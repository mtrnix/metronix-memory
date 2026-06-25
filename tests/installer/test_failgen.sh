#!/usr/bin/env bash
# Verify install.sh aborts (and never launches) when secret generation fails.
# Run: bash tests/installer/test_failgen.sh
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

run_case() {
  local override="$1"; shift
  local dir; dir="$(mktemp -d)"
  printf 'LLM_PROVIDER=ollama\nOLLAMA_CHAT_MODEL=\nPOSTGRES_PASSWORD=changeme\nNEO4J_PASSWORD=changeme\nMETRONIX_MCP_API_KEY=changeme\nFERNET_KEY=changeme\n' > "$dir/.env.example"
  cat > "$dir/run.sh" <<EOF
source "$INSTALL"
check_prereqs() { :; }
launch() { echo "LAUNCHED"; }
wait_health() { :; }
print_links() { :; }
$override
REPO_ROOT="$dir"
main "\$@"
EOF
  ( cd "$dir" && bash run.sh "$@" >/tmp/installer_failgen_out.txt 2>&1 ); LAST_RC=$?; LAST_DIR="$dir"
}

abort_checks() {
  chk "exit nonzero (aborted)" "$([[ $LAST_RC -ne 0 ]] && echo yes || echo no)" "yes"
  chk "did NOT launch"         "$(grep -q LAUNCHED /tmp/installer_failgen_out.txt && echo launched || echo no)" "no"
  chk "no .env left"           "$([[ -f "$LAST_DIR/.env" ]] && echo exists || echo absent)" "absent"
}

echo "Scenario A: gen_secret hard-FAILS (returns non-zero, empty output)"
run_case 'gen_secret() { return 1; }' -y
abort_checks

echo "Scenario B: gen_secret returns 0 but EMPTY string"
run_case 'gen_secret() { printf ""; return 0; }' -y
abort_checks

echo "Scenario C: gen_fernet fails -> must also abort"
run_case 'gen_fernet() { return 1; }' -y
abort_checks

echo "Scenario D: happy path still works (real generators)"
run_case ':' -y
chk "exit zero"   "$LAST_RC" "0"
chk "launched"    "$(grep -q LAUNCHED /tmp/installer_failgen_out.txt && echo launched || echo no)" "launched"
chk ".env exists" "$([[ -f "$LAST_DIR/.env" ]] && echo exists || echo absent)" "exists"
if [[ -f "$LAST_DIR/.env" ]]; then
  plen=$(grep '^POSTGRES_PASSWORD=' "$LAST_DIR/.env" | cut -d= -f2- | tr -d '\n' | wc -c | tr -d ' ')
  chk "POSTGRES_PASSWORD non-empty" "$([[ $plen -gt 0 ]] && echo yes || echo no)" "yes"
fi

echo ""
echo "TOTAL: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
