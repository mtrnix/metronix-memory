#!/usr/bin/env bash
# install.sh --quickstart hands off to scripts/quickstart.sh, so the already
# deployed bootstrap reaches it with: bash -s -- -- --quickstart
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
chk() {
  if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi
}

cp "$ROOT/install.sh" "$TMP/install.sh"
mkdir -p "$TMP/scripts"
printf '#!/usr/bin/env bash\nprintf "QS:%%s\\n" "$*"\n' > "$TMP/scripts/quickstart.sh"

out="$(bash "$TMP/install.sh" --quickstart 2>&1)"
chk "--quickstart runs scripts/quickstart.sh" "$(grep '^QS:' <<<"$out")" "QS:--"

out="$(bash "$TMP/install.sh" --admin --quickstart --with-graph-model 2>&1)"
chk "other options are forwarded to the installer" "$(grep '^QS:' <<<"$out")" "QS:-- --admin --with-graph-model"

rm "$TMP/scripts/quickstart.sh"
out="$(bash "$TMP/install.sh" --quickstart 2>&1)"; rc=$?
chk "missing quickstart.sh fails with exit 1" "$rc" "1"

echo "TOTAL: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
