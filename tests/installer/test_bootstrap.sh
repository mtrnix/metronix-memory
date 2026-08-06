#!/usr/bin/env bash
# Offline behavior tests for scripts/install-bootstrap.sh.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOOTSTRAP="$ROOT/scripts/install-bootstrap.sh"
TMP="$(mktemp -d)"
REMOTE="$TMP/remote.git"
SOURCE="$TMP/source"
PASS=0; FAIL=0

chk() {
  if [[ "$2" == "$3" ]]; then
    echo "  PASS: $1"; PASS=$((PASS+1))
  else
    echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1))
  fi
}

run_bootstrap() {
  if ! METRONIX_REPO_URL="$REMOTE" bash "$BOOTSTRAP" "$@" >"$OUT" 2>&1; then
    cat "$OUT" >&2
    return 1
  fi
}

git init --bare "$REMOTE" >/dev/null
git init -b main "$SOURCE" >/dev/null
git -C "$SOURCE" config user.name test
git -C "$SOURCE" config user.email test@example.invalid
git -C "$SOURCE" remote add origin "$REMOTE"
printf '#!/usr/bin/env bash\nprintf "ARGS:%%s\\n" "$*"\n' > "$SOURCE/install.sh"
chmod +x "$SOURCE/install.sh"
git -C "$SOURCE" add install.sh
git -C "$SOURCE" commit -m v1 >/dev/null
git -C "$SOURCE" tag v1.0.0
git -C "$SOURCE" push -u origin main --tags >/dev/null

DEST="$TMP/install"
OUT="$TMP/out"

BROKEN="$TMP/incomplete"
git init "$BROKEN" >/dev/null
run_bootstrap --dir "$BROKEN" -- -y
chk "incomplete checkout is replaced safely" "$(grep '^ARGS:' "$OUT")" "ARGS:-y"
chk "incomplete checkout is preserved" "$(find "$TMP" -maxdepth 1 -type d -name 'incomplete.incomplete-*' | wc -l | tr -d ' ')" "1"

run_bootstrap --dir "$DEST" -- --mode memory -y
chk "latest tag clones successfully" "$?" "0"
chk "installer arguments forwarded" "$(grep '^ARGS:' "$OUT")" "ARGS:--mode memory -y"
chk "tag checkout is detached" "$(git -C "$DEST" symbolic-ref -q --short HEAD || echo detached)" "detached"

printf '#!/usr/bin/env bash\nprintf "V2:%%s\\n" "$*"\n' > "$SOURCE/install.sh"
git -C "$SOURCE" add install.sh
git -C "$SOURCE" commit -m v2 >/dev/null
git -C "$SOURCE" tag v2.0.0
git -C "$SOURCE" push origin main --tags >/dev/null
run_bootstrap --update --dir "$DEST" -- -y
chk "update installs newest tag" "$(grep '^V2:' "$OUT")" "V2:-y"

printf 'local note\n' > "$DEST/local-note.txt"
run_bootstrap --update --dir "$DEST" -- -y
chk "untracked local files survive update" "$(cat "$DEST/local-note.txt")" "local note"
chk "temporary stash is removed after restore" "$(git -C "$DEST" stash list | wc -l | tr -d ' ')" "0"

set +e
METRONIX_REPO_URL="$REMOTE" bash "$BOOTSTRAP" --branch main --version v1.0.0 --dir "$TMP/bad" >"$OUT" 2>&1
RC=$?
set -e
chk "conflicting selectors fail" "$([[ $RC -eq 2 ]] && echo yes || echo no)" "yes"

echo "$PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
