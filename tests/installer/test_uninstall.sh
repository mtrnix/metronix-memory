#!/usr/bin/env bash
# Offline behavior tests for uninstall.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
WORK="$TMP/repo"
mkdir -p "$WORK"
cp "$ROOT/uninstall.sh" "$WORK/uninstall.sh"
UNINSTALL="$WORK/uninstall.sh"

passed=0
failed=0
chk() {
  local label="$1" got="$2" expected="$3"
  if [[ "$got" == "$expected" ]]; then
    printf '  PASS: %s\n' "$label"
    passed=$((passed + 1))
  else
    printf '  FAIL: %s\n    expected: %s\n    got:      %s\n' "$label" "$expected" "$got"
    failed=$((failed + 1))
  fi
}

stub="$TMP/bin"
mkdir -p "$stub"
# shellcheck disable=SC2016 # Fixture text must preserve variables for the stub process.
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'if [[ "$1 $2" == "compose version" ]]; then' \
  '  exit 0' \
  'fi' \
  'printf '\''%s\n'\'' "$*" >> "$DOCKER_LOG"' \
  > "$stub/docker"
chmod +x "$stub/docker"

run() {
  : > "$TMP/docker.log"
  HOME="$TMP/home" PATH="$stub:$PATH" DOCKER_LOG="$TMP/docker.log" bash "$UNINSTALL" "$@" > "$TMP/out" 2>&1
}

run
chk "default includes optional profiles" "$(cat "$TMP/docker.log")" \
  "compose --profile admin --profile openwebui --profile benchmarker down"

run --volumes
chk "--volumes deletes data volumes" "$(cat "$TMP/docker.log")" \
  "compose --profile admin --profile openwebui --profile benchmarker down -v"

mkdir -p "$WORK/metronix-hermes-setup"
printf 'secret\n' > "$WORK/.env"
mkdir -p "$TMP/home/.hermes" "$TMP/home/.codex"
printf 'mcp_servers:\n  metronix:\n    url: http://localhost:8000/mcp\n  other:\n    url: http://other\n' > "$TMP/home/.hermes/config.yaml"
printf 'before\n--- metronix-config ---\nremove me\n--- end metronix-config ---\nafter\n' > "$TMP/home/.hermes/SOUL.md"
printf '[mcp_servers.metronix]\nurl = "http://localhost:8000/mcp"\n\n[other]\nkey = "value"\n' > "$TMP/home/.codex/config.toml"
run --purge
chk "--purge preserves Docker volumes" "$(cat "$TMP/docker.log")" \
  "compose --profile admin --profile openwebui --profile benchmarker down"
chk "--purge removes generated env" "$(test ! -e "$WORK/.env" && echo yes || echo no)" "yes"
chk "--purge removes setup guides" "$(test ! -e "$WORK/metronix-hermes-setup" && echo yes || echo no)" "yes"
chk "--purge removes only the Hermes MCP entry" "$(grep -c '^  other:' "$TMP/home/.hermes/config.yaml")" "1"
chk "--purge removes Hermes marker block" "$(grep -c -- 'metronix-config' "$TMP/home/.hermes/SOUL.md" || true)" "0"
chk "--purge removes only the Codex MCP table" "$(grep -c '^\[other\]$' "$TMP/home/.codex/config.toml")" "1"

if [[ "$failed" -gt 0 ]]; then
  printf '%s passed, %s failed\n' "$passed" "$failed"
  exit 1
fi
printf '%s passed, 0 failed\n' "$passed"
