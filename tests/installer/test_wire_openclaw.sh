#!/usr/bin/env bash
# Tests for the OpenClaw wiring in install.sh. Sandboxed; no real ~/.openclaw.
# The CLI-edit path uses a fake `openclaw` stub on PATH — no real OpenClaw needed.
# Run: bash tests/installer/test_wire_openclaw.sh
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
REPO="$(dirname "$INSTALL")"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

echo "Task3: flag parses into global, usage lists it"
out="$(bash -c "source '$INSTALL'; parse_args --wire-openclaw --agent-id abc123; echo \"\$WIRE_OPENCLAW|\$AGENT_ID\"")"
chk "flag parsed" "$out" "true|abc123"
chk "usage lists --wire-openclaw" "$(bash -c "source '$INSTALL'; usage" | grep -c -- '--wire-openclaw')" "1"
chk "WIRE_OPENCLAW defaults false" "$(bash -c "source '$INSTALL'; echo \$WIRE_OPENCLAW")" "false"

echo "Task4: detection helpers"
hd="$(mktemp -d)"
chk "openclaw_found: neither binary nor dir -> false" "$(HOME="$hd" PATH="/usr/bin:/bin" bash -c "source '$INSTALL'; openclaw_found && echo yes || echo no")" "no"
mkdir -p "$hd/.openclaw"
chk "openclaw_found: dir only -> true" "$(HOME="$hd" bash -c "source '$INSTALL'; openclaw_found && echo yes || echo no")" "yes"
chk "openclaw_cli_available: dir only, no binary -> false" "$(HOME="$hd" PATH="/usr/bin:/bin" bash -c "source '$INSTALL'; openclaw_cli_available && echo yes || echo no")" "no"
stub="$(mktemp -d)"; printf '#!/usr/bin/env bash\nexit 0\n' > "$stub/openclaw"; chmod +x "$stub/openclaw"
chk "openclaw_cli_available: binary on PATH -> true" "$(HOME="$hd" PATH="$stub:$PATH" bash -c "source '$INSTALL'; openclaw_cli_available && echo yes || echo no")" "yes"

echo "Task4b: json_escape / openclaw_mcp_json"
chk "json_escape: plain string unchanged" "$(bash -c "source '$INSTALL'; json_escape 'plain'")" "plain"
chk "json_escape: escapes quote and backslash" "$(bash -c "source '$INSTALL'; json_escape 'a\"b\\c'")" 'a\"b\\c'
payload="$(bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY123; H_AGENT=AID9; openclaw_mcp_json")"
chk "payload has url" "$(printf '%s' "$payload" | grep -c 'http://h:8000/mcp')" "1"
chk "payload has bearer key" "$(printf '%s' "$payload" | grep -c 'Bearer KEY123')" "1"
chk "payload has agent header" "$(printf '%s' "$payload" | grep -c 'X-Agent-Id":"AID9')" "1"
chk "payload has streamable-http transport" "$(printf '%s' "$payload" | grep -c 'streamable-http')" "1"
chk "payload is one line" "$(printf '%s' "$payload" | wc -l | tr -d ' ')" "0"

echo "Task5: fake openclaw CLI stub"
# Stub layout: $STUB_DIR/openclaw is the fake binary. It stores the "current MCP
# server" state as JSON in $OPENCLAW_STUB_DIR/metronix.json. `mcp show metronix`
# prints it (exit 1 if absent). `mcp set metronix <json>` writes it (exit 1 if
# $OPENCLAW_STUB_DIR/FAIL_SET exists, to simulate a CLI failure).
make_openclaw_stub() {
  local stub_dir="$1"
  mkdir -p "$stub_dir"
  cat > "$stub_dir/openclaw" <<'STUB'
#!/usr/bin/env bash
set -u
state="$OPENCLAW_STUB_DIR/metronix.json"
case "${1:-} ${2:-}" in
  "mcp show")
    [[ "${3:-}" == metronix ]] || exit 1
    [[ -f "$state" ]] || exit 1
    cat "$state"
    ;;
  "mcp set")
    [[ "${3:-}" == metronix ]] || { echo "unsupported name" >&2; exit 1; }
    [[ -f "$OPENCLAW_STUB_DIR/FAIL_SET" ]] && { echo "simulated failure" >&2; exit 1; }
    printf '%s' "${4:-}" > "$state"
    ;;
  *)
    echo "unsupported: $*" >&2; exit 1
    ;;
esac
STUB
  chmod +x "$stub_dir/openclaw"
}

echo "Task5a: openclaw_mcp_state classifies absent / same-url / different-url"
stub3="$(mktemp -d)"; make_openclaw_stub "$stub3"
osd="$(mktemp -d)"
chk "state: absent" "$(PATH="$stub3:$PATH" OPENCLAW_STUB_DIR="$osd" bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; openclaw_mcp_state")" "none"
printf '{"url":"http://h:8000/mcp"}' > "$osd/metronix.json"
chk "state: same url" "$(PATH="$stub3:$PATH" OPENCLAW_STUB_DIR="$osd" bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; openclaw_mcp_state")" "has_same_url"
printf '{"url":"http://other:9/mcp"}' > "$osd/metronix.json"
chk "state: different url" "$(PATH="$stub3:$PATH" OPENCLAW_STUB_DIR="$osd" bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; openclaw_mcp_state")" "has_different"

echo "Task5b: wire_openclaw orchestrator (HOME stubbed)"
STUB_ENV='get_env(){ case $1 in METRONIX_MCP_API_KEY) echo K;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }'

# absent OpenClaw -> prompt dir, no ~/.openclaw created.
# PATH is sandboxed to /usr/bin:/bin here and in the next case — a real `openclaw`
# CLI may be installed on the machine running these tests, and without a minimal
# PATH it would leak through openclaw_cli_available, causing wire_openclaw to skip
# the "not found" branch and actually invoke the real `openclaw mcp set` against
# the developer's real ~/.openclaw/openclaw.json. That must never happen from a test.
hd="$(mktemp -d)"; work="$(mktemp -d)"; cp "$REPO/prompts.md" "$work/prompts.md"
( cd "$work" && HOME="$hd" PATH="/usr/bin:/bin" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_OPENCLAW=true; $STUB_ENV; wire_openclaw" >/tmp/wo1.txt 2>&1 )
chk "absent -> prompt dir" "$([[ -d "$work/metronix-agent-setup" ]] && echo yes || echo no)" "yes"
chk "absent -> no ~/.openclaw" "$([[ -e "$hd/.openclaw" ]] && echo yes || echo no)" "no"

# present (dir only, no CLI) + --wire-openclaw -y -> guide only, no crash
hd2="$(mktemp -d)"; mkdir -p "$hd2/.openclaw"; work2="$(mktemp -d)"; cp "$REPO/prompts.md" "$work2/prompts.md"
( cd "$work2" && HOME="$hd2" PATH="/usr/bin:/bin" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_OPENCLAW=true; $STUB_ENV; wire_openclaw" >/tmp/wo2.txt 2>&1 )
chk "dir-only, no CLI -> prompt dir" "$([[ -d "$work2/metronix-agent-setup" ]] && echo yes || echo no)" "yes"

# present + CLI + -y --wire-openclaw -> MCP registered, SOUL.md wired, prompt dir written
hd3="$(mktemp -d)"; mkdir -p "$hd3/.openclaw"; stub3b="$(mktemp -d)"; make_openclaw_stub "$stub3b"; osd3="$(mktemp -d)"
work3="$(mktemp -d)"; cp "$REPO/prompts.md" "$work3/prompts.md"
( cd "$work3" && HOME="$hd3" PATH="$stub3b:$PATH" OPENCLAW_STUB_DIR="$osd3" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_OPENCLAW=true; ${STUB_ENV/echo K/echo KEYZ}; wire_openclaw" >/tmp/wo3.txt 2>&1 )
chk "mcp registered" "$(grep -c 'Bearer KEYZ' "$osd3/metronix.json")" "1"
chk "soul wired" "$(grep -c -- '--- metronix-config ---' "$hd3/.openclaw/workspace/SOUL.md")" "1"
chk "apply also wrote prompts dir" "$([[ -f "$work3/metronix-agent-setup/prompts.md" ]] && echo yes || echo no)" "yes"

# idempotent re-run -> mcp set not re-invoked (content must still reflect the
# ORIGINAL run's values even if H_KEY changed, proving we skipped the second
# `set` call)
( cd "$work3" && HOME="$hd3" PATH="$stub3b:$PATH" OPENCLAW_STUB_DIR="$osd3" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_OPENCLAW=true; ${STUB_ENV/echo K/echo DIFFERENTKEY}; wire_openclaw" >/tmp/wo3b.txt 2>&1 )
chk "idempotent: second run does not overwrite" "$(grep -c 'Bearer KEYZ' "$osd3/metronix.json")" "1"
chk "idempotent: second run did not use the new key" "$(grep -c 'DIFFERENTKEY' "$osd3/metronix.json")" "0"

# CLI failure -> guide fallback, no partial SOUL.md write
hd4="$(mktemp -d)"; mkdir -p "$hd4/.openclaw"; stub4="$(mktemp -d)"; make_openclaw_stub "$stub4"; osd4="$(mktemp -d)"
mkdir -p "$osd4"; touch "$osd4/FAIL_SET"
work4="$(mktemp -d)"; cp "$REPO/prompts.md" "$work4/prompts.md"
( cd "$work4" && HOME="$hd4" PATH="$stub4:$PATH" OPENCLAW_STUB_DIR="$osd4" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_OPENCLAW=true; ${STUB_ENV/echo K/echo KEYQ}; wire_openclaw" >/tmp/wo4.txt 2>&1 )
chk "CLI failure -> guide written" "$([[ -d "$work4/metronix-agent-setup" ]] && echo yes || echo no)" "yes"
chk "CLI failure -> no SOUL.md written" "$([[ -f "$hd4/.openclaw/workspace/SOUL.md" ]] && echo yes || echo no)" "no"

# bare -y (no --wire-openclaw) -> guide only, nothing registered
hd5="$(mktemp -d)"; mkdir -p "$hd5/.openclaw"; stub5="$(mktemp -d)"; make_openclaw_stub "$stub5"; osd5="$(mktemp -d)"
work5="$(mktemp -d)"; cp "$REPO/prompts.md" "$work5/prompts.md"
( cd "$work5" && HOME="$hd5" PATH="$stub5:$PATH" OPENCLAW_STUB_DIR="$osd5" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_OPENCLAW=false; $STUB_ENV; wire_openclaw" >/tmp/wo5.txt 2>&1 )
chk "bare -y -> not registered" "$([[ -f "$osd5/metronix.json" ]] && echo yes || echo no)" "no"
chk "bare -y -> prompt dir written" "$([[ -d "$work5/metronix-agent-setup" ]] && echo yes || echo no)" "yes"

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
