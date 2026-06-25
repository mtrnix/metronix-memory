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

echo "Task3: templates substitute values, no placeholders"
tpl="$(bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY123; H_AGENT=AID9; H_WS=MTRNIX; hermes_config_block; echo ---; hermes_soul_block; echo ---; hermes_prompt_doc")"
chk "no leftover {{ }}" "$(printf '%s' "$tpl" | grep -c '{{')" "0"
chk "config has url" "$(printf '%s' "$tpl" | grep -c 'http://h:8000/mcp')" "2"
# hermes_prompt_doc embeds hermes_config_block + hermes_soul_block, so each
# pattern appears twice in the combined output (once from the direct call, once
# from the embedded expansion inside hermes_prompt_doc). Count 2 is correct.
chk "config has bearer key" "$(printf '%s' "$tpl" | grep -c 'Bearer KEY123')" "2"
chk "config has agent header" "$(printf '%s' "$tpl" | grep -c 'X-Agent-Id: AID9')" "2"
chk "soul has workspace" "$(printf '%s' "$tpl" | grep -c 'workspace_id="MTRNIX"')" "2"
chk "soul block delimited" "$(printf '%s' "$tpl" | grep -c -- '--- metronix-config ---')" "2"

echo "Task4: SOUL.md append/replace"
d="$(mktemp -d)"; printf 'You are Persona.\nLine two.\n' > "$d/SOUL.md"
bash -c "source '$INSTALL'; H_URL=u; H_KEY=k; H_AGENT=a1; H_WS=MTRNIX; merge_soul_block '$d/SOUL.md'"
chk "persona preserved" "$(grep -c 'You are Persona.' "$d/SOUL.md")" "1"
chk "block appended once" "$(grep -c -- '--- metronix-config ---' "$d/SOUL.md")" "1"
# second run with a different agent id must REPLACE, not duplicate
bash -c "source '$INSTALL'; H_URL=u; H_KEY=k; H_AGENT=a2; H_WS=MTRNIX; merge_soul_block '$d/SOUL.md'"
chk "still single block" "$(grep -c -- '--- metronix-config ---' "$d/SOUL.md")" "1"
chk "id updated in place" "$(grep -c 'agent_id="a2"' "$d/SOUL.md")" "1"
chk "old id gone" "$(grep -c 'agent_id="a1"' "$d/SOUL.md")" "0"
chk "persona still there" "$(grep -c 'You are Persona.' "$d/SOUL.md")" "1"

echo "Task4b: orphan opening marker (no end marker) must not drop trailing content"
d="$(mktemp -d)"; printf 'Persona top.\n--- metronix-config ---\nPersona AFTER orphan opener.\n' > "$d/SOUL.md"
bash -c "source '$INSTALL'; H_URL=u; H_KEY=k; H_AGENT=ax; H_WS=MTRNIX; merge_soul_block '$d/SOUL.md'"
chk "orphan: top persona kept" "$(grep -c 'Persona top.' "$d/SOUL.md")" "1"
chk "orphan: trailing persona kept" "$(grep -c 'Persona AFTER orphan opener.' "$d/SOUL.md")" "1"
chk "orphan: a complete block now present" "$(grep -c -- '--- end metronix-config ---' "$d/SOUL.md")" "1"

# Helper: can we actually run yq (host binary, or Docker daemon up for mikefarah/yq)?
can_run_yq() { command -v yq >/dev/null 2>&1 || { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }; }

echo "Task5a: merge_hermes_config builds the right Docker yq command (host yq absent)"
if command -v yq >/dev/null 2>&1; then
  echo "  SKIP 5a: host yq present — Docker branch not taken here"
else
  d="$(mktemp -d)"; printf 'mcp_servers: {}\n' > "$d/config.yaml"
  out="$(bash -c "source '$INSTALL'; docker(){ echo DOCKER \"\$@\"; }; H_URL=http://h/v1; H_KEY=K1; H_AGENT=A1; merge_hermes_config '$d/config.yaml'")"
  chk "5a invokes docker once" "$(printf '%s' "$out" | grep -c '^DOCKER run')" "1"
  chk "5a passes -e H_URL" "$(printf '%s' "$out" | grep -c -- '-e H_URL=http://h/v1')" "1"
  chk "5a passes -e H_AGENT" "$(printf '%s' "$out" | grep -c -- '-e H_AGENT=A1')" "1"
  chk "5a runs mikefarah/yq -i" "$(printf '%s' "$out" | grep -c 'mikefarah/yq -i')" "1"
  chk "5a mounts a work dir" "$(printf '%s' "$out" | grep -c -- '-w /work')" "1"
fi

echo "Task5b: real merge edits config (host yq or Docker), preserving other keys"
if can_run_yq; then
  d="$(mktemp -d)"; printf 'agent: hermes\nmcp_servers:\n  other:\n    url: http://other\n' > "$d/config.yaml"
  bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY1; H_AGENT=AID1; H_WS=MTRNIX; merge_hermes_config '$d/config.yaml'" >/dev/null 2>&1
  chk "5b metronix url set" "$(grep -c 'url: http://h:8000/mcp' "$d/config.yaml")" "1"
  chk "5b auth header set" "$(grep -c 'Authorization: Bearer KEY1' "$d/config.yaml")" "1"
  chk "5b agent header set" "$(grep -c 'X-Agent-Id: AID1' "$d/config.yaml")" "1"
  chk "5b other server preserved" "$(grep -c 'url: http://other' "$d/config.yaml")" "1"
  chk "5b top-level preserved" "$(grep -c '^agent: hermes' "$d/config.yaml")" "1"
else
  echo "  SKIP 5b: no host yq and no usable Docker — real merge not exercised"
fi

echo "Task6: prompt-file fallback"
d="$(mktemp -d)"
bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY1; H_AGENT=AID1; H_WS=MTRNIX; write_hermes_prompt_file '$d/setup.md'" >/dev/null
chk "file written" "$([[ -f "$d/setup.md" ]] && echo yes || echo no)" "yes"
chk "contains config block" "$(grep -c 'X-Agent-Id: AID1' "$d/setup.md")" "1"
chk "contains soul block" "$(grep -c -- '--- metronix-config ---' "$d/setup.md")" "1"
chk "no placeholders" "$(grep -c '{{' "$d/setup.md")" "0"

echo "Task7: orchestrator (HOME stubbed)"
# absent Hermes -> prompt file, no ~/.hermes created
hd="$(mktemp -d)"; work="$(mktemp -d)"
( cd "$work" && HOME="$hd" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; METRONIX_MCP_API_KEY=K; DEFAULT_WORKSPACE_ID=MTRNIX; get_env(){ case \$1 in METRONIX_MCP_API_KEY) echo K;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }; wire_hermes" >/tmp/wh.txt 2>&1 )
chk "absent -> prompt file" "$([[ -f "$work/metronix-hermes-setup.md" ]] && echo yes || echo no)" "yes"
chk "absent -> no ~/.hermes" "$([[ -e "$hd/.hermes" ]] && echo yes || echo no)" "no"
# present + -y --wire-hermes -> edits applied (real yq via host or Docker)
if can_run_yq; then
  hd2="$(mktemp -d)"; mkdir -p "$hd2/.hermes"; printf 'agent: hermes\n' > "$hd2/.hermes/config.yaml"; printf 'Persona.\n' > "$hd2/.hermes/SOUL.md"
  ( HOME="$hd2" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; get_env(){ case \$1 in METRONIX_MCP_API_KEY) echo KEYZ;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }; wire_hermes" >/tmp/wh2.txt 2>&1 )
  chk "config wired" "$(grep -c 'Authorization: Bearer KEYZ' "$hd2/.hermes/config.yaml")" "1"
  chk "soul wired" "$(grep -c -- '--- metronix-config ---' "$hd2/.hermes/SOUL.md")" "1"
  chk "backup made" "$(ls "$hd2/.hermes/"config.yaml.bak-* 2>/dev/null | wc -l | tr -d ' ')" "1"
  chk "no leftover temp files" "$(ls "$hd2/.hermes/".metronix-* 2>/dev/null | wc -l | tr -d ' ')" "0"
else
  echo "  SKIP: no host yq and no usable Docker — apply path not exercised"
fi

echo "Task8: standalone --wire-hermes does not build the stack"
hd="$(mktemp -d)"; work="$(mktemp -d)"; cp "$INSTALL" "$work/install.sh"
printf 'METRONIX_MCP_API_KEY=K\nDEFAULT_WORKSPACE_ID=MTRNIX\n' > "$work/.env"
( cd "$work" && HOME="$hd" bash -c "source ./install.sh; launch(){ echo BUILT; }; wait_health(){ :; }; print_links(){ :; }; check_prereqs(){ :; }; main --wire-hermes -y" >/tmp/wh3.txt 2>&1 )
chk "standalone did NOT build" "$(grep -q BUILT /tmp/wh3.txt && echo built || echo no)" "no"
chk "standalone wrote prompt or wired" "$([[ -f "$work/metronix-hermes-setup.md" || -f "$hd/.hermes/config.yaml" ]] && echo yes || echo no)" "yes"

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
