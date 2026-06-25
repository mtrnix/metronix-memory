#!/usr/bin/env bash
# Behaviour tests for install.sh configure() — sandboxed, no docker required.
# Run: bash tests/installer/test_install.sh
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

# Run install.sh in a throwaway dir with the heavy steps stubbed, so only
# parse_args + configure are exercised. launch() echoes state for assertions.
run_case() {
  local dir; dir="$(mktemp -d)"
  printf 'LLM_PROVIDER=ollama\nLLM_PROVIDER_URL=\nLLM_PROVIDER_API_KEY=\nLLM_PROVIDER_MODEL=\nOLLAMA_CHAT_MODEL=\nPOSTGRES_PASSWORD=changeme\nNEO4J_PASSWORD=changeme\nMETRONIX_MCP_API_KEY=changeme\nFERNET_KEY=changeme\n' > "$dir/.env.example"
  cat > "$dir/run.sh" <<EOF
source "$INSTALL"
check_prereqs() { :; }
launch() { echo "LAUNCHED webui=\$ENABLE_WEBUI"; }
wait_health() { :; }
print_links() { :; }
REPO_ROOT="$dir"
main "\$@"
EOF
  ( cd "$dir" && bash run.sh "$@" >/tmp/installer_test_out.txt 2>&1 ); LAST_RC=$?; LAST_DIR="$dir"
}
envval()   { grep "^$1=" "$LAST_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-; }
launched() { grep -q LAUNCHED /tmp/installer_test_out.txt && echo yes || echo no; }
has_env()  { [[ -f "$LAST_DIR/.env" ]] && echo yes || echo no; }

echo "Case 1: default -y -> memory mode"
run_case -y
chk "exit zero" "$LAST_RC" "0"
chk "launched" "$(launched)" "yes"
chk "LLM_PROVIDER=ollama" "$(envval LLM_PROVIDER)" "ollama"
chk "OLLAMA_CHAT_MODEL empty" "$(envval OLLAMA_CHAT_MODEL)" ""
chk "no leftover staging" "$(ls "$LAST_DIR"/.env.?????? 2>/dev/null | wc -l | tr -d ' ')" "0"

echo "Case 2: answers via flags (url+model+key)"
run_case -y --mode answers --chat-url https://api.deepseek.com/v1 --chat-model deepseek-chat --chat-api-key sk-xyz
chk "exit zero" "$LAST_RC" "0"
chk "launched" "$(launched)" "yes"
chk "LLM_PROVIDER=custom" "$(envval LLM_PROVIDER)" "custom"
chk "URL set" "$(envval LLM_PROVIDER_URL)" "https://api.deepseek.com/v1"
chk "MODEL set" "$(envval LLM_PROVIDER_MODEL)" "deepseek-chat"
chk "API key set" "$(envval LLM_PROVIDER_API_KEY)" "sk-xyz"
chk "OLLAMA_CHAT_MODEL stays empty" "$(envval OLLAMA_CHAT_MODEL)" ""

echo "Case 3: --chat-url implies answers; no key = blank (optional)"
run_case -y --chat-url http://host.docker.internal:11434/v1 --chat-model llama3.1:8b
chk "exit zero" "$LAST_RC" "0"
chk "LLM_PROVIDER=custom (inferred)" "$(envval LLM_PROVIDER)" "custom"
chk "URL set" "$(envval LLM_PROVIDER_URL)" "http://host.docker.internal:11434/v1"
chk "API key blank (optional)" "$(envval LLM_PROVIDER_API_KEY)" ""

echo "Case 4: --mode answers WITHOUT --chat-url -> abort, no .env"
run_case -y --mode answers --chat-model x
chk "exit nonzero" "$([[ $LAST_RC -ne 0 ]] && echo yes || echo no)" "yes"
chk "did not launch" "$(launched)" "no"
chk "no .env left" "$(has_env)" "no"

echo "Case 5: answers, url given but model missing -> abort, no .env"
run_case -y --mode answers --chat-url https://api.deepseek.com/v1
chk "exit nonzero" "$([[ $LAST_RC -ne 0 ]] && echo yes || echo no)" "yes"
chk "no .env left" "$(has_env)" "no"

echo "Case 6: bad --mode -> abort"
run_case -y --mode bogus
chk "exit nonzero" "$([[ $LAST_RC -ne 0 ]] && echo yes || echo no)" "yes"
chk "no .env left" "$(has_env)" "no"

echo "Case 7: --openwebui in memory mode -> ignored with warning, still launches"
run_case -y --openwebui
chk "exit zero" "$LAST_RC" "0"
chk "launched" "$(launched)" "yes"
chk "warns about ignoring" "$(grep -qi 'ignoring --openwebui' /tmp/installer_test_out.txt && echo yes || echo no)" "yes"
chk "webui disabled" "$(grep -q 'webui=false' /tmp/installer_test_out.txt && echo yes || echo no)" "yes"

echo "Case 8: --openwebui in answers mode -> honored"
run_case -y --openwebui --chat-url https://api.deepseek.com/v1 --chat-model deepseek-chat
chk "exit zero" "$LAST_RC" "0"
chk "no ignore warning" "$(grep -qi 'ignoring --openwebui' /tmp/installer_test_out.txt && echo yes || echo no)" "no"
chk "webui enabled" "$(grep -q 'webui=true' /tmp/installer_test_out.txt && echo yes || echo no)" "yes"

echo ""
echo "TOTAL: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
