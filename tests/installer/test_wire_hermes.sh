#!/usr/bin/env bash
# Tests for the Hermes wiring in install.sh. Sandboxed; no real ~/.hermes.
# The text-merge / apply paths need a usable yq or Docker and SKIP otherwise.
set -u
INSTALL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install.sh"
REPO="$(dirname "$INSTALL")"
PASS=0; FAIL=0
chk() { if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (got [$2] want [$3])"; FAIL=$((FAIL+1)); fi; }

echo "Task1: flags parse into globals"
out="$(bash -c "source '$INSTALL'; parse_args --wire-hermes --agent-id abc123 --metronix-url http://x:8000/mcp --fresh-docker-reset; echo \"\$WIRE_HERMES|\$AGENT_ID|\$METRONIX_URL|\$FRESH_DOCKER_RESET\"")"
chk "flags parsed" "$out" "true|abc123|http://x:8000/mcp|true"
chk "usage lists --wire-hermes" "$(bash -c "source '$INSTALL'; usage" | grep -c -- '--wire-hermes')" "1"
chk "usage lists --fresh-docker-reset" "$(bash -c "source '$INSTALL'; usage" | grep -c -- '--fresh-docker-reset')" "1"

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

echo "Task2b: persisted METRONIX_AGENT_ID in .env is reused; live Hermes config still wins"
da="$(mktemp -d)"; printf 'METRONIX_AGENT_ID=persistaaaabbbbccccddddeeee00001\n' > "$da/.env"
r4="$(cd "$da" && bash -c "source '$INSTALL'; AGENT_ID=''; resolve_agent_id '$da/none.yaml'")"
chk "reuses persisted .env id when no Hermes config" "$r4" "persistaaaabbbbccccddddeeee00001"
r5="$(cd "$da" && bash -c "source '$INSTALL'; AGENT_ID=''; resolve_agent_id '$d/config.yaml'")"
chk "live Hermes config id wins over persisted .env id" "$r5" "deadbeefdeadbeefdeadbeefdeadbeef"
rm -rf "$da"

echo "Task3: auto-edit blocks render with substituted values"
tpl="$(bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY123; H_AGENT=AID9; H_WS=MTRNIX; hermes_config_block; echo ---; hermes_soul_block")"
chk "config has url" "$(printf '%s' "$tpl" | grep -c 'http://h:8000/mcp')" "1"
chk "config has bearer key" "$(printf '%s' "$tpl" | grep -c 'Bearer KEY123')" "1"
chk "config has agent header" "$(printf '%s' "$tpl" | grep -c 'X-Agent-Id: AID9')" "1"
chk "soul has workspace" "$(printf '%s' "$tpl" | grep -c 'workspace_id="MTRNIX"')" "1"
chk "soul block delimited" "$(printf '%s' "$tpl" | grep -c -- '--- metronix-config ---')" "1"

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

# Can we actually run yq (host binary, or Docker daemon up for mikefarah/yq)?
can_run_yq() { command -v yq >/dev/null 2>&1 || { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }; }

echo "Task5: minimal text merge -- append / insert / idempotent (gated on yq/Docker)"
if can_run_yq; then
  # 5a) no mcp_servers -> append block at EOF; original lines stay byte-identical
  d="$(mktemp -d)"; printf 'agent: hermes\ntoolsets:\n- hermes-cli\n' > "$d/c.yaml"; cp "$d/c.yaml" "$d/orig"
  bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY1; H_AGENT=AID1; merge_hermes_config '$d/c.yaml'" >/dev/null 2>&1
  chk "5a metronix appended" "$(grep -c '^  metronix:' "$d/c.yaml")" "1"
  chk "5a url set" "$(grep -c 'url: http://h:8000/mcp' "$d/c.yaml")" "1"
  chk "5a NO reformat (toolsets item intact)" "$(grep -c '^- hermes-cli' "$d/c.yaml")" "1"
  chk "5a original prefix untouched" "$(diff <(cat "$d/orig") <(head -3 "$d/c.yaml") >/dev/null 2>&1 && echo same || echo changed)" "same"

  # 5b) existing mcp_servers -> insert metronix under it; siblings + non-mcp lines unchanged
  d2="$(mktemp -d)"; printf 'agent: hermes\nmcp_servers:\n  other:\n    url: http://other\ntoolsets:\n- hermes-cli\n' > "$d2/c.yaml"
  bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY2; H_AGENT=AID2; merge_hermes_config '$d2/c.yaml'" >/dev/null 2>&1
  chk "5b metronix inserted" "$(grep -c '^  metronix:' "$d2/c.yaml")" "1"
  chk "5b other server preserved" "$(grep -c 'url: http://other' "$d2/c.yaml")" "1"
  chk "5b NO reformat (toolsets item intact)" "$(grep -c '^- hermes-cli' "$d2/c.yaml")" "1"

  # 5c) idempotent: re-running makes no change, no duplicate
  bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY2; H_AGENT=AID2; merge_hermes_config '$d2/c.yaml'" >/dev/null 2>&1
  chk "5c single metronix entry" "$(grep -c '^  metronix:' "$d2/c.yaml")" "1"
else
  echo "  SKIP Task5: no host yq and no usable Docker -- text merge not exercised"
fi

echo "Task6: prompt dir -- 4 filled prompts, no unfilled placeholders"
d="$(mktemp -d)"
bash -c "source '$INSTALL'; H_URL=http://h:8000/mcp; H_KEY=KEY1; H_AGENT=AID1; H_WS=MTRNIX; write_hermes_prompt_dir '$d/out'" >/dev/null 2>&1
chk "4 files written" "$(ls -1 "$d/out" 2>/dev/null | wc -l | tr -d ' ')" "4"
chk "prompt 1 filled (agent)" "$(grep -c 'X-Agent-Id: AID1' "$d/out/1-install-mcp.md")" "1"
chk "prompt 2 present" "$([[ -f "$d/out/2-memory-source.md" ]] && echo yes || echo no)" "yes"
chk "prompt 3 present" "$([[ -f "$d/out/3-migrate.md" ]] && echo yes || echo no)" "yes"
chk "prompt 4 (rollback) present" "$([[ -f "$d/out/4-rollback.md" ]] && echo yes || echo no)" "yes"
chk "prompt 4 filled (workspace + agent)" "$([[ $(grep -c 'workspace_id="MTRNIX"' "$d/out/4-rollback.md") -ge 1 && $(grep -c 'agent_id="AID1"' "$d/out/4-rollback.md") -ge 1 ]] && echo yes || echo no)" "yes"
chk "no unfilled real placeholders" "$(grep -rlE '\{\{(METRONIX_URL|METRONIX_MCP_API_KEY|AGENT_UUID|DEFAULT_WORKSPACE_ID)\}\}' "$d/out" 2>/dev/null | wc -l | tr -d ' ')" "0"

echo "Task7: orchestrator (HOME stubbed)"
STUB_ENV='get_env(){ case $1 in METRONIX_MCP_API_KEY) echo K;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }'

# absent Hermes -> prompt dir, no ~/.hermes created
hd="$(mktemp -d)"; work="$(mktemp -d)"
( cd "$work" && HOME="$hd" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; $STUB_ENV; wire_hermes" >/tmp/wh.txt 2>&1 )
chk "absent -> prompt dir" "$([[ -d "$work/metronix-agent-setup" ]] && echo yes || echo no)" "yes"
chk "absent -> no ~/.hermes" "$([[ -e "$hd/.hermes" ]] && echo yes || echo no)" "no"

# present + interactive choice "2" -> guide only, config NOT edited (no yq needed)
hd3="$(mktemp -d)"; w3="$(mktemp -d)"; mkdir -p "$hd3/.hermes"; printf 'agent: hermes\n' > "$hd3/.hermes/config.yaml"
( cd "$w3" && HOME="$hd3" bash -c "source '$INSTALL'; ASSUME_YES=false; WIRE_HERMES=false; $STUB_ENV; wire_hermes" >/tmp/wh3.txt 2>&1 <<< "2" )
chk "choice 2 -> prompt dir written" "$([[ -d "$w3/metronix-agent-setup" ]] && echo yes || echo no)" "yes"
chk "choice 2 -> config NOT edited" "$(grep -c 'metronix:' "$hd3/.hermes/config.yaml")" "0"

# present + bare -y (no --wire-hermes) -> guide only, config NOT edited
hd4="$(mktemp -d)"; w4="$(mktemp -d)"; mkdir -p "$hd4/.hermes"; printf 'agent: hermes\n' > "$hd4/.hermes/config.yaml"
( cd "$w4" && HOME="$hd4" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=false; $STUB_ENV; wire_hermes" >/tmp/wh4.txt 2>&1 )
chk "bare -y -> config NOT edited" "$(grep -c 'metronix:' "$hd4/.hermes/config.yaml")" "0"
chk "bare -y -> prompt dir written" "$([[ -d "$w4/metronix-agent-setup" ]] && echo yes || echo no)" "yes"

# present + -y --wire-hermes -> minimal edit applied + prompts dir written (real yq via host/Docker)
if can_run_yq; then
  hd2="$(mktemp -d)"; w2="$(mktemp -d)"; mkdir -p "$hd2/.hermes"; printf 'agent: hermes\n' > "$hd2/.hermes/config.yaml"; printf 'Persona.\n' > "$hd2/.hermes/SOUL.md"
  ( cd "$w2" && HOME="$hd2" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; ${STUB_ENV/echo K/echo KEYZ}; wire_hermes" >/tmp/wh2.txt 2>&1 )
  chk "config wired" "$(grep -c 'Bearer KEYZ' "$hd2/.hermes/config.yaml")" "1"
  chk "config NOT reformatted (agent line intact)" "$(grep -c '^agent: hermes' "$hd2/.hermes/config.yaml")" "1"
  chk "soul wired" "$(grep -c -- '--- metronix-config ---' "$hd2/.hermes/SOUL.md")" "1"
  chk "backup made" "$(ls "$hd2/.hermes/"config.yaml.bak-* 2>/dev/null | wc -l | tr -d ' ')" "1"
  chk "no leftover temp files" "$(ls "$hd2/.hermes/".metronix-* 2>/dev/null | wc -l | tr -d ' ')" "0"
  chk "apply also wrote prompts dir (2 & 3 ready)" "$([[ -f "$w2/metronix-agent-setup/2-memory-source.md" ]] && echo yes || echo no)" "yes"
else
  echo "  SKIP: no host yq and no usable Docker -- apply path not exercised"
fi

echo "Task8: standalone --wire-hermes does not build the stack"
hd="$(mktemp -d)"; work="$(mktemp -d)"; cp "$INSTALL" "$work/install.sh"
mkdir -p "$work/docs/integrations/hermes"; cp "$REPO/docs/integrations/hermes/"prompt-*.md "$work/docs/integrations/hermes/"
printf 'METRONIX_MCP_API_KEY=K\nDEFAULT_WORKSPACE_ID=MTRNIX\n' > "$work/.env"
( cd "$work" && HOME="$hd" bash -c "source ./install.sh; launch(){ echo BUILT; }; wait_health(){ :; }; print_links(){ :; }; check_prereqs(){ :; }; main --wire-hermes -y" >/tmp/wh5.txt 2>&1 )
chk "standalone did NOT build" "$(grep -q BUILT /tmp/wh5.txt && echo built || echo no)" "no"
chk "standalone produced prompts or wired" "$([[ -d "$work/metronix-agent-setup" || -f "$hd/.hermes/config.yaml" ]] && echo yes || echo no)" "yes"

echo "Task8b: wire_hermes anchors METRONIX_AGENT_ID in .env and keeps it stable"
agent_id1="$(grep '^METRONIX_AGENT_ID=' "$work/.env" | cut -d= -f2-)"
chk "agent id persisted to .env" "$(printf '%s' "$agent_id1" | grep -cE '^[0-9a-f]{32}$')" "1"
( cd "$work" && HOME="$hd" bash -c "source ./install.sh; launch(){ :; }; wait_health(){ :; }; print_links(){ :; }; check_prereqs(){ :; }; main --wire-hermes -y" >/tmp/wh6.txt 2>&1 )
chk "agent id stable across re-run" "$(grep '^METRONIX_AGENT_ID=' "$work/.env" | cut -d= -f2-)" "$agent_id1"

echo "Task9: fresh ~/.hermes (dir exists, but no config.yaml/SOUL.md yet) must not crash"
hd9="$(mktemp -d)"; mkdir -p "$hd9/.hermes"
w9="$(mktemp -d)"
if can_run_yq; then
  ( cd "$w9" && HOME="$hd9" bash -c "source '$INSTALL'; ASSUME_YES=true; WIRE_HERMES=true; get_env(){ case \$1 in METRONIX_MCP_API_KEY) echo KFRESH;; DEFAULT_WORKSPACE_ID) echo MTRNIX;; esac; }; wire_hermes" >/tmp/wh9.txt 2>&1 )
  chk "no crash: wiring-completed message printed" "$(grep -c 'Wired Metronix into Hermes' /tmp/wh9.txt)" "1"
  chk "config.yaml created fresh" "$(grep -c 'Bearer KFRESH' "$hd9/.hermes/config.yaml")" "1"
  chk "SOUL.md created fresh" "$(grep -c -- '--- metronix-config ---' "$hd9/.hermes/SOUL.md")" "1"
else
  echo "  SKIP Task9: no host yq and no usable Docker -- apply path not exercised"
fi

echo ""; echo "TOTAL: $PASS passed, $FAIL failed"; [[ $FAIL -eq 0 ]]
