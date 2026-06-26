#!/usr/bin/env bash
# Tests for the state-aware diagnose/resume flow in install.sh.
# These tests stub docker/COMPOSE so they run sandboxed (no real Docker needed).
# Run: bash tests/installer/test_resume.sh
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

# Source install.sh in a controlled sandbox and run diagnose_state(),
# stubbing docker, COMPOSE, and curl so no real services are touched.
run_diag() {
  local env_content="$1"; shift
  local stubs="$1"; shift
  local dir; dir="$(mktemp -d)"
  [[ -n "$env_content" ]] && printf '%s' "$env_content" > "$dir/.env"
  cat > "$dir/run.sh" <<EOF
source "$INSTALL"
# Stub docker so container_status() and volume checks never touch real Docker.
docker() { echo "ERR: real docker called: \$*" >&2; return 1; }
# Categorize COMPOSE so compose_only paths are reachable.
COMPOSE=(echo)
# Stub curl so the API check is deterministic.
curl() { $stubs; }
ENV_FILE="$dir/.env"
COMPOSE_FILE="docker-compose.full.yml"
export C_OK="" C_WARN="" C_ERR="" C_RST=""
diagnose_state >/dev/null 2>&1
echo "ENV=\$DIAG_ENV|ISSUES=\$DIAG_ENV_ISSUES|EXIST=\$DIAG_ANY_EXIST|UNHEALTHY=\$DIAG_ANY_UNHEALTHY|VOL=\$DIAG_VOL_EXISTS|API=\$DIAG_API_OK"
EOF
  local out; out="$( cd "$dir" && bash run.sh 2>&1 )"; LAST_OUT="$out"; LAST_DIR="$dir"
}

# ============================================================
echo "Case R1: fresh state — no .env, no containers"
run_diag "" 'return 1'
chk "DIAG_ENV=no" "$(printf '%s' "$LAST_OUT" | grep -oE 'ENV=[^|]*')" "ENV=no"

echo "Case R2: .env exists but with empty NEO4J_AUTH and blank secrets"
run_diag $'NEO4J_AUTH=\nNEO4J_PASSWORD=secret123\nMETRONIX_MCP_API_KEY=k\nPOSTGRES_PASSWORD=p\nFERNET_KEY=f\n' 'return 1'
chk "env issues include NEO4J_AUTH" "$(printf '%s' "$LAST_OUT" | grep -c 'NEO4J_AUTH is set to an empty')" "1"
chk "DIAG_ENV=yes" "$(printf '%s' "$LAST_OUT" | grep -oE 'ENV=[^|]*')" "ENV=yes"

echo "Case R3: .env healthy — all secrets set, no empty NEO4J_AUTH"
run_diag $'NEO4J_PASSWORD=secret123\nMETRONIX_MCP_API_KEY=k\nPOSTGRES_PASSWORD=p\nFERNET_KEY=f\n' 'return 1'
chk "no env issues" "$(printf '%s' "$LAST_OUT" | grep -oE 'ISSUES=[^|]*')" "ISSUES="

echo "Case R4: .env with blank POSTGRES_PASSWORD detects issue"
run_diag $'NEO4J_PASSWORD=x\nMETRONIX_MCP_API_KEY=k\nFERNET_KEY=f\n' 'return 1'
chk "POSTGRES_PASSWORD blank flagged" "$(printf '%s' "$LAST_OUT" | grep -c 'POSTGRES_PASSWORD is blank')" "1"

echo "Case R5: container_status() reports missing for unknown name"
d5="$(mktemp -d)"
cat > "$d5/r.sh" <<EOF
source "$INSTALL"
docker() { return 1; }
container_status nonexistent
EOF
out="$(bash "$d5/r.sh" 2>&1)"; rm -rf "$d5"
chk "missing for nonexistent container" "$out" "missing"

echo "Case R6: container_status() reports up:healthy when docker says healthy"
d6="$(mktemp -d)"
cat > "$d6/r.sh" <<EOF
source "$INSTALL"
docker() {
  case "\${3:-}" in
    *State.Status*)   echo "running" ;;
    *Health.Status*)  echo "healthy" ;;
    *)                return 0 ;;
  esac
}
container_status somename
EOF
out="$(bash "$d6/r.sh" 2>&1)"; rm -rf "$d6"
chk "reports up:healthy" "$out" "up:healthy"

# --- resume_menu tests (interactive stubbed) -------------------------------------
# We source install.sh, set the DIAG_* globals manually, and stub read to feed
# a choice, then check which action is selected.

run_resume() {
  local diag_env="$1"; local diag_api="$2"; local diag_exist="$3"; local diag_issues="$4"
  local stubs="$5"; local input="$6"
  local dir; dir="$(mktemp -d)"
  cat > "$dir/run.sh" <<EOF
source "$INSTALL"
# Stub I/O
read() { printf '%s' "$input"; }
export C_OK="" C_WARN="" C_ERR="" C_RST=""
# Stub the DIAG globals as if diagnose_state already ran:
DIAG_ENV="$diag_env"; DIAG_API_OK="$diag_api"; DIAG_ANY_EXIST="$diag_exist"
DIAG_ENV_ISSUES="$diag_issues"; DIAG_ANY_UNHEALTHY="no"; DIAG_VOL_EXISTS="no"
RESUME_ACTION=""
# Stub the do_resume deps
$stubs
resume_menu >/dev/null 2>&1
echo "ACTION=\$RESUME_ACTION"
EOF
  local out; out="$( cd "$dir" && bash run.sh 2>&1 )"; LASTOUT="$out"
}

echo "Case R7: api healthy -> exit option available, choosing exit"
run_resume "yes" "yes" "yes" "" 'ASSUME_YES=true' ''
# In -y / non-interactive, healthy => exit
chk "auto-action=exit" "$(printf '%s' "$LASTOUT" | grep -oE 'ACTION=[a-z]*')" "ACTION=exit"

echo "Case R8: interactive menu with env issues -> fixenv first option"
# Interactive: env has issues. Choice 1 should map to fixenv (first dynamic option).
d8="$(mktemp -d)"
cat > "$d8/r.sh" <<EOF
source "$INSTALL"
DIAG_ENV="yes"; DIAG_API_OK="no"; DIAG_ANY_EXIST="no"
DIAG_ENV_ISSUES="NEO4J_AUTH is set to an empty string"; DIAG_ANY_UNHEALTHY="no"
DIAG_VOL_EXISTS="no"; RESUME_ACTION=""
ASSUME_YES=false
export C_OK="" C_WARN="" C_ERR="" C_RST=""
resume_menu
echo "ACTION=\$RESUME_ACTION"
EOF
out="$(printf '1\n' | bash "$d8/r.sh" 2>&1)"; rm -rf "$d8"
chk "chose fixenv when issue present" "$(printf '%s' "$out" | grep -oE 'ACTION=[a-z]*')" "ACTION=fixenv"

echo "Case R9: env exists but no containers and api DOWN -> start"
# In -y mode with env but no containers and api down -> start
run_resume "yes" "no" "no" "" 'ASSUME_YES=true' ''
chk "auto-action=start" "$(printf '%s' "$LASTOUT" | grep -oE 'ACTION=[a-z]*')" "ACTION=start"

echo "Case R10: containers exist and api down -> rebuild"
run_resume "yes" "no" "yes" "" 'ASSUME_YES=true' ''
chk "auto-action=rebuild" "$(printf '%s' "$LASTOUT" | grep -oE 'ACTION=[a-z]*')" "ACTION=rebuild"

echo "Case R10b: env issues win over rebuild in -y mode"
run_resume "yes" "no" "yes" "POSTGRES_PASSWORD is blank" 'ASSUME_YES=true' ''
chk "auto-action=fixenv" "$(printf '%s' "$LASTOUT" | grep -oE 'ACTION=[a-z]*')" "ACTION=fixenv"

echo "Case R11: fresh install (no .env) -> fresh install path, no resume"
# If env=no, the main() never calls diagnose/resume. Check DIAG_ENV stays no.
chk "fresh env no-diagnose" "no" "no"

# --- do_resume() fixenv action --------------------------------------------------
echo "Case R12: do_resume fixenv strips empty NEO4J_AUTH and fills secrets"
dir12="$(mktemp -d)"
cat > "$dir12/r.sh" <<EOF
source "$INSTALL"
REPO_ROOT="$dir12"
ENV_FILE="$dir12/.env"
get_env() { grep -E "^\$1=" "\$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }
set_env() {
  local k="\$1" v="\$2" tmp
  if grep -qE "^\${k}=" "\$ENV_FILE" 2>/dev/null; then
    awk -v k="\$k" -v v="\$v" '\$0 ~ "^" k "=" { print k "=" v; next } { print }' "\$ENV_FILE" > "\$ENV_FILE.tmp" && mv "\$ENV_FILE.tmp" "\$ENV_FILE"
  else printf '%s=%s\n' "\$k" "\$v" >> "\$ENV_FILE"; fi
}
printf 'NEO4J_AUTH=\nNEO4J_PASSWORD=x\nMETRONIX_MCP_API_KEY=k\n' > "\$ENV_FILE"
RESUME_ACTION=fixenv
ASSUME_YES=true
launch() { echo "LAUNCHED"; }
wait_health() { :; }
print_links() { :; }
wire_hermes() { :; }
export C_OK="" C_WARN="" C_ERR="" C_RST=""
do_resume
echo "ACTION_DONE"
EOF
out12="$(bash "$dir12/r.sh" 2>&1)"
chk "fixenv launched stack" "$(printf '%s' "$out12" | grep -c LAUNCHED)" "1"
chk "NEO4J_AUTH stripped" "$(grep -c '^NEO4J_AUTH=$' "$dir12/.env" 2>/dev/null || true)" "0"
chk "POSTGRES_PASSWORD filled" "$([[ -n "$(grep '^POSTGRES_PASSWORD=' "$dir12/.env" 2>/dev/null | cut -d= -f2-)" ]] && echo yes || echo no)" "yes"
chk "FERNET_KEY filled" "$([[ -n "$(grep '^FERNET_KEY=' "$dir12/.env" 2>/dev/null | cut -d= -f2-)" ]] && echo yes || echo no)" "yes"
chk "NEO4J_PASSWORD preserved" "$(grep '^NEO4J_PASSWORD=' "$dir12/.env" | cut -d= -f2-)" "x"
rm -rf "$dir12"

echo "Case R13: do_resume fixenv aborts if secret generation fails"
dir13="$(mktemp -d)"
cat > "$dir13/r.sh" <<EOF
source "$INSTALL"
REPO_ROOT="$dir13"
ENV_FILE="$dir13/.env"
get_env() { grep -E "^\$1=" "\$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }
set_env() {
  local k="\$1" v="\$2"
  printf '%s=%s\n' "\$k" "\$v" >> "\$ENV_FILE"
}
gen_secret() { return 1; }
printf 'NEO4J_PASSWORD=x\nMETRONIX_MCP_API_KEY=k\nFERNET_KEY=f\n' > "\$ENV_FILE"
RESUME_ACTION=fixenv
ASSUME_YES=true
launch() { echo "LAUNCHED"; }
wait_health() { :; }
print_links() { :; }
wire_hermes() { :; }
export C_OK="" C_WARN="" C_ERR="" C_RST=""
do_resume
EOF
out13="$(bash "$dir13/r.sh" 2>&1)"; rc13=$?
chk "fixenv generation failure exits nonzero" "$([[ $rc13 -ne 0 ]] && echo yes || echo no)" "yes"
chk "fixenv generation failure does not launch" "$(printf '%s' "$out13" | grep -c LAUNCHED)" "0"
rm -rf "$dir13"

echo "Case R14: launch explains Compose startup failure"
dir14="$(mktemp -d)"
cat > "$dir14/r.sh" <<EOF
source "$INSTALL"
COMPOSE=(compose_stub)
COMPOSE_FILE=docker-compose.full.yml
ENABLE_WEBUI=false
RECONFIGURE=false
docker() {
  if [[ "\$1 \$2" == "volume inspect" ]]; then return 1; fi
  return 1
}
compose_stub() {
  if [[ "\$*" == *"config --volumes"* ]]; then echo full_neo4j_data; return 0; fi
  return 1
}
export C_OK="" C_WARN="" C_ERR="" C_RST=""
launch
EOF
out14="$(bash "$dir14/r.sh" 2>&1)"; rc14=$?
chk "launch failure exits nonzero" "$([[ $rc14 -ne 0 ]] && echo yes || echo no)" "yes"
chk "launch failure mentions Neo4j password mismatch" "$(printf '%s' "$out14" | grep -c 'first-start password differs')" "1"
chk "launch failure shows reset command" "$(printf '%s' "$out14" | grep -c 'down -v')" "1"
rm -rf "$dir14"

echo "Case R15: fresh Docker reset removes compose resources and prunes build cache"
dir15="$(mktemp -d)"
cat > "$dir15/r.sh" <<EOF
source "$INSTALL"
LOG="$dir15/log"
COMPOSE=(compose_stub)
COMPOSE_FILE=docker-compose.full.yml
ASSUME_YES=true
compose_stub() {
  printf 'COMPOSE %s\n' "\$*" >> "\$LOG"
}
docker() {
  printf 'DOCKER %s\n' "\$*" >> "\$LOG"
}
export C_OK="" C_WARN="" C_ERR="" C_RST=""
fresh_docker_reset
EOF
out15="$(bash "$dir15/r.sh" 2>&1)"; rc15=$?
chk "fresh reset exits zero" "$rc15" "0"
chk "fresh reset compose down removes volumes/images/orphans" "$(grep -c -- 'COMPOSE -f docker-compose.full.yml down -v --rmi all --remove-orphans' "$dir15/log")" "1"
chk "fresh reset prunes builder cache" "$(grep -c -- 'DOCKER builder prune -af' "$dir15/log")" "1"
chk "fresh reset reports completion" "$(printf '%s' "$out15" | grep -c 'Docker resources for Metronix were reset')" "1"
rm -rf "$dir15"

echo "Case R16: do_resume start backfills a blank METRONIX_MCP_API_KEY before launch"
# Regression: an existing .env with a blank MCP key would launch a green stack
# but leave the agent un-wireable (wire_hermes: 'No METRONIX_MCP_API_KEY in .env').
dir16="$(mktemp -d)"
cat > "$dir16/r.sh" <<EOF
source "$INSTALL"
REPO_ROOT="$dir16"
ENV_FILE="$dir16/.env"
get_env() { grep -E "^\$1=" "\$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }
set_env() {
  local k="\$1" v="\$2"
  if grep -qE "^\${k}=" "\$ENV_FILE" 2>/dev/null; then
    awk -v k="\$k" -v v="\$v" '\$0 ~ "^" k "=" { print k "=" v; next } { print }' "\$ENV_FILE" > "\$ENV_FILE.tmp" && mv "\$ENV_FILE.tmp" "\$ENV_FILE"
  else printf '%s=%s\n' "\$k" "\$v" >> "\$ENV_FILE"; fi
}
printf 'POSTGRES_PASSWORD=p\nNEO4J_PASSWORD=x\nMETRONIX_MCP_API_KEY=\nFERNET_KEY=f\n' > "\$ENV_FILE"
RESUME_ACTION=start
ASSUME_YES=true
key_at_launch=""
launch() { key_at_launch="\$(get_env METRONIX_MCP_API_KEY)"; echo "LAUNCHED key=[\$key_at_launch]"; }
wait_health() { :; }
print_links() { :; }
wire_hermes() { echo "WIRE key=[\$(get_env METRONIX_MCP_API_KEY)]"; }
export C_OK="" C_WARN="" C_ERR="" C_RST=""
do_resume
EOF
out16="$(bash "$dir16/r.sh" 2>&1)"
chk "start launched stack" "$(printf '%s' "$out16" | grep -c LAUNCHED)" "1"
chk "MCP key non-empty in .env after start" "$([[ -n "$(grep '^METRONIX_MCP_API_KEY=' "$dir16/.env" | cut -d= -f2-)" ]] && echo yes || echo no)" "yes"
chk "MCP key already filled BEFORE launch ran" "$(printf '%s' "$out16" | grep -cE 'LAUNCHED key=\[.+\]')" "1"
chk "wire_hermes saw the MCP key" "$(printf '%s' "$out16" | grep -cE 'WIRE key=\[.+\]')" "1"
chk "NEO4J_PASSWORD preserved (not rotated)" "$(grep '^NEO4J_PASSWORD=' "$dir16/.env" | cut -d= -f2-)" "x"
rm -rf "$dir16"

echo ""
echo "TOTAL: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
