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
  printf 'LLM_PROVIDER=ollama\nLLM_PROVIDER_URL=\nLLM_PROVIDER_API_KEY=\nLLM_PROVIDER_MODEL=\nOLLAMA_LLM_MODEL=qwen2.5:3b\nPOSTGRES_PASSWORD=changeme\nNEO4J_PASSWORD=changeme\nMETRONIX_MCP_API_KEY=changeme\nFERNET_KEY=changeme\nMETRONIX_SECRET_KEY=develop-secret-key-change-in-prod\nNEO4J_AUTH=\n' > "$dir/.env.example"
  cat > "$dir/run.sh" <<EOF
source "$INSTALL"
check_prereqs() { :; }
# Sandbox: never touch real Docker. Without this the orphan-volume guard in
# configure() would see the developer's real Metronix volumes and abort.
docker() { return 1; }
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
chk "OLLAMA_LLM_MODEL default kept" "$(envval OLLAMA_LLM_MODEL)" "qwen2.5:3b"
chk "no leftover staging" "$(ls "$LAST_DIR"/.env.?????? 2>/dev/null | wc -l | tr -d ' ')" "0"

echo "Case 2: answers via flags (url+model+key)"
run_case -y --mode answers --chat-url https://api.deepseek.com/v1 --chat-model deepseek-chat --chat-api-key sk-xyz
chk "exit zero" "$LAST_RC" "0"
chk "launched" "$(launched)" "yes"
chk "LLM_PROVIDER=custom" "$(envval LLM_PROVIDER)" "custom"
chk "URL set" "$(envval LLM_PROVIDER_URL)" "https://api.deepseek.com/v1"
chk "MODEL set" "$(envval LLM_PROVIDER_MODEL)" "deepseek-chat"
chk "API key set" "$(envval LLM_PROVIDER_API_KEY)" "sk-xyz"
chk "OLLAMA_LLM_MODEL default kept" "$(envval OLLAMA_LLM_MODEL)" "qwen2.5:3b"

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

echo "Case 9: NEO4J_AUTH= (empty) stripped from generated .env"
run_case -y
chk "exit zero" "$LAST_RC" "0"
chk "NO empty NEO4J_AUTH=" "$(grep -c '^NEO4J_AUTH=$' "$LAST_DIR/.env" 2>/dev/null || true)" "0"
chk "NEO4J_PASSWORD set non-empty" "$([[ -n "$(envval NEO4J_PASSWORD)" ]] && echo yes || echo no)" "yes"
chk "NEO4J_PASSWORD not the placeholder" "$([[ "$(envval NEO4J_PASSWORD)" != "changeme" ]] && echo yes || echo no)" "yes"

echo "Case 10: NEO4J_PASSWORD preserved across --reconfigure"
# Simulate a second run: .env exists with a real neo4j password, --reconfigure
printf 'LLM_PROVIDER=ollama\nNEO4J_PASSWORD=my_saved_password\nMETRONIX_MCP_API_KEY=K\n' > "$LAST_DIR/.env"
( cd "$LAST_DIR" && bash run.sh -y --reconfigure >/tmp/installer_test_out.txt 2>&1 ); LAST_RC=$?
chk "exit zero" "$LAST_RC" "0"
chk "NEO4J_PASSWORD preserved" "$(envval NEO4J_PASSWORD)" "my_saved_password"

echo "Case 11: METRONIX_SECRET_KEY placeholder is rotated on a fresh install"
run_case -y
chk "exit zero" "$LAST_RC" "0"
chk "SECRET_KEY non-empty" "$([[ -n "$(envval METRONIX_SECRET_KEY)" ]] && echo yes || echo no)" "yes"
chk "SECRET_KEY not the shipped placeholder" "$([[ "$(envval METRONIX_SECRET_KEY)" != "develop-secret-key-change-in-prod" ]] && echo yes || echo no)" "yes"

echo "Case 12: a real (non-placeholder) METRONIX_SECRET_KEY survives --reconfigure"
printf 'LLM_PROVIDER=ollama\nNEO4J_PASSWORD=p\nMETRONIX_MCP_API_KEY=K\nMETRONIX_SECRET_KEY=my-real-prod-secret\n' > "$LAST_DIR/.env"
( cd "$LAST_DIR" && bash run.sh -y --reconfigure >/tmp/installer_test_out.txt 2>&1 ); LAST_RC=$?
chk "exit zero" "$LAST_RC" "0"
chk "SECRET_KEY preserved" "$(envval METRONIX_SECRET_KEY)" "my-real-prod-secret"

echo "Case 13: full reset (--fresh-docker-reset) regenerates DB passwords, preserves other secrets"
# The volume is gone after the reset, so reusing the old .env password would only
# perpetuate a stale/broken credential. A fresh reset must produce a fresh password.
run_case -y
printf 'LLM_PROVIDER=ollama\nPOSTGRES_PASSWORD=oldpg_real\nNEO4J_PASSWORD=oldneo_real\nMETRONIX_MCP_API_KEY=keepmcp\nFERNET_KEY=keepfernet\nMETRONIX_SECRET_KEY=keepsecret\n' > "$LAST_DIR/.env"
( cd "$LAST_DIR" && bash run.sh -y --fresh-docker-reset >/tmp/installer_test_out.txt 2>&1 ); LAST_RC=$?
chk "exit zero" "$LAST_RC" "0"
chk "NEO4J_PASSWORD regenerated (not reused)" "$([[ "$(envval NEO4J_PASSWORD)" != "oldneo_real" && -n "$(envval NEO4J_PASSWORD)" ]] && echo yes || echo no)" "yes"
chk "POSTGRES_PASSWORD regenerated (not reused)" "$([[ "$(envval POSTGRES_PASSWORD)" != "oldpg_real" && -n "$(envval POSTGRES_PASSWORD)" ]] && echo yes || echo no)" "yes"
chk "MCP key preserved across reset" "$(envval METRONIX_MCP_API_KEY)" "keepmcp"
chk "SECRET_KEY preserved across reset" "$(envval METRONIX_SECRET_KEY)" "keepsecret"

echo "Case 14: full reset that failed to remove the volume aborts (no mismatched password written)"
# down -v can silently fail; if the volume survived, regenerating would recreate the
# exact mismatch bug. The orphan-volume guard must catch it instead.
d14="$(mktemp -d)"
printf 'LLM_PROVIDER=ollama\nPOSTGRES_PASSWORD=changeme\nNEO4J_PASSWORD=changeme\nMETRONIX_MCP_API_KEY=changeme\nFERNET_KEY=changeme\nMETRONIX_SECRET_KEY=develop-secret-key-change-in-prod\n' > "$d14/.env.example"
printf 'LLM_PROVIDER=ollama\nPOSTGRES_PASSWORD=oldpg_real\nNEO4J_PASSWORD=oldneo_real\nMETRONIX_MCP_API_KEY=k\nFERNET_KEY=f\nMETRONIX_SECRET_KEY=s\n' > "$d14/.env"
cat > "$d14/run.sh" <<EOF
source "$INSTALL"
check_prereqs() { COMPOSE=(docker compose); }
# down -v "failed": the neo4j volume STILL exists after the reset.
docker() { if [[ "\$1 \$2" == "volume ls" ]]; then printf '%s\n' metronix-memory_full_neo4j_data; return 0; fi; return 1; }
launch() { echo "LAUNCHED (should not happen)"; }
wait_health() { :; }
print_links() { :; }
connect_agent() { :; }
REPO_ROOT="$d14"
main -y --fresh-docker-reset
EOF
( cd "$d14" && bash run.sh >/tmp/installer_test_out14.txt 2>&1 ); rc14=$?
chk "aborts nonzero when volume survived reset" "$([[ $rc14 -ne 0 ]] && echo yes || echo no)" "yes"
chk "did not launch a mismatched stack" "$(grep -c LAUNCHED /tmp/installer_test_out14.txt)" "0"
chk "guidance shown" "$(grep -c 'cannot be recovered' /tmp/installer_test_out14.txt)" "1"
chk "real .env password left untouched" "$(grep '^NEO4J_PASSWORD=' "$d14/.env" | cut -d= -f2-)" "oldneo_real"
rm -rf "$d14"

echo ""
echo "TOTAL: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
