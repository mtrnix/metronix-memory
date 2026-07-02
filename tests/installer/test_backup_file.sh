#!/usr/bin/env bash
# _backup_file is called bare (no `|| true`) by every connect_* runtime
# (Hermes, Claude Code, Codex, OpenClaw). It must never return nonzero on a
# missing target — under `set -e`, a bare nonzero-returning call aborts the
# whole installer. This test protects that invariant directly, once, for
# every caller, instead of one regression test per runtime.
# Run: bash tests/installer/test_backup_file.sh
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

echo "Task1: _backup_file on a missing file must return 0 (never crash a bare caller)"
d="$(mktemp -d)"
out="$(bash -c "set -euo pipefail; source '$INSTALL'; _backup_file '$d/does-not-exist'; echo reached" 2>&1)"
chk "bare call does not trip set -e" "$out" "reached"
chk "no backup file created" "$(ls "$d" 2>/dev/null | wc -l | tr -d ' ')" "0"

echo "Task2: _backup_file on an existing file creates exactly one timestamped backup"
d2="$(mktemp -d)"; printf 'original content\n' > "$d2/config"
bash -c "set -euo pipefail; source '$INSTALL'; _backup_file '$d2/config'"
chk "exactly one backup created" "$(ls "$d2"/config.bak-* 2>/dev/null | wc -l | tr -d ' ')" "1"
chk "backup content matches original" "$(cat "$d2"/config.bak-* 2>/dev/null)" "original content"
chk "original file untouched" "$(cat "$d2/config")" "original content"

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
