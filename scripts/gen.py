#!/usr/bin/env python3
"""Generate one synthetic artifact via oMLX for the demo-data workflow."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:8090")
API_KEY = os.environ.get("OMLX_API_KEY", "")
DEBUG_CoT = os.environ.get("OMLX_LOG_REASONING", "") not in ("", "0", "false")
ENDPOINT = f"{BASE}/v1/chat/completions"

KIND_DEFAULTS = {
    "jira": ("qwen-opus", 0.4, 2000, "schema"),
    # Defects: switched off qwen36-a3b — its 1-3k token CoT-burn caused finish_reason=length
    # at max_tokens=4500. qwen-opus handles defect structure (Observed/Expected/Repro/Workaround)
    # fine since the prompt template is pre-baked. Bumped to 3000 just in case.
    "jira_defect": ("qwen-opus", 0.4, 3000, "schema"),
    "jira_req": ("qwen-opus", 0.4, 2500, "schema"),
    "confluence": ("qwen-opus", 0.7, 3500, "none"),
    "skeleton": ("gemma-4", 0.3, 2500, "none"),
    "readme": ("qwen-opus", 0.6, 1500, "none"),
}


def post(payload: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


def call_once(messages, model, temperature, max_tokens, json_mode, schema):
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if json_mode == "schema" and schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": schema}
    elif json_mode == "object":
        payload["response_format"] = {"type": "json_object"}
    body = post(payload)
    choice = body["choices"][0]
    msg = choice["message"]
    if choice.get("finish_reason") == "length":
        raise RuntimeError(
            f"truncated (model={model}, "
            f"completion_tokens={body.get('usage', {}).get('completion_tokens')}). "
            f"Increase max_tokens."
        )
    if DEBUG_CoT and msg.get("reasoning_content"):
        rc = msg["reasoning_content"]
        print(f"  CoT [{model}] {len(rc)} chars: {rc[:160]!r}…", file=sys.stderr)
    return msg["content"] or ""


def call_with_fallback(messages, model, temperature, max_tokens, json_mode, schema):
    levels = {
        "schema": ["schema", "object", "none"],
        "object": ["object", "none"],
        "none": ["none"],
    }.get(json_mode, ["none"])
    last_err = None
    for level in levels:
        try:
            text = call_once(messages, model, temperature, max_tokens, level, schema)
            if level != json_mode:
                print(
                    f"  note: server rejected json_mode={json_mode}, used {level}", file=sys.stderr
                )
            return text, level
        except urllib.error.HTTPError as e:
            last_err = f"{e.code} {e.reason}: {e.read()[:300].decode(errors='replace')}"
            continue
    raise RuntimeError(f"all json_mode levels failed: {last_err}")


def stem_of(meta_path: Path) -> Path:
    return meta_path.with_suffix("").with_suffix("")


def generate(stem: Path) -> None:
    meta = json.loads(stem.with_suffix(".meta.json").read_text())
    kind = meta["kind"]
    out = Path(meta["out"])
    if out.exists():
        print(f"skip   {out} (exists)")
        return
    if kind not in KIND_DEFAULTS:
        raise ValueError(f"unknown kind={kind!r}; expected one of {list(KIND_DEFAULTS)}")
    default_model, default_temp, default_max, default_jm = KIND_DEFAULTS[kind]
    model = meta.get("model", default_model)
    json_mode = meta.get("json_mode", default_jm)
    temp = meta.get("temperature", default_temp)
    max_toks = meta.get("max_tokens", default_max)

    sys_paths = [Path(f"prompts/system/{kind}.system.txt")]
    if "_" in kind:
        sys_paths.append(Path(f"prompts/system/{kind.split('_')[0]}.system.txt"))
    system_prompt = next((p.read_text() for p in sys_paths if p.exists()), None)
    if system_prompt is None:
        raise FileNotFoundError(f"no system prompt for kind={kind!r}; tried {sys_paths}")

    user_prompt = stem.with_suffix(".user.txt").read_text()

    sch_paths = [Path(f"prompts/schemas/{kind}.schema.json")]
    if "_" in kind:
        sch_paths.append(Path(f"prompts/schemas/{kind.split('_')[0]}.schema.json"))
    schema_path = next((p for p in sch_paths if p.exists()), None)
    schema = json.loads(schema_path.read_text()) if schema_path else None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    t0 = time.time()
    text, used = call_with_fallback(messages, model, temp, max_toks, json_mode, schema)

    if json_mode in ("schema", "object"):
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"non-JSON response despite json_mode={json_mode} (used={used}): {e}"
            ) from e

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote  {out}  [{model}/{used}]  {len(text)}b  {time.time() - t0:.1f}s")


def main(argv: list[str]) -> int:
    target = Path(argv[1])
    if target.is_dir():
        metas = sorted(target.glob("*.meta.json"))
        if not metas:
            print(f"no *.meta.json files under {target}", file=sys.stderr)
            return 2
        for m in metas:
            try:
                generate(stem_of(m))
            except Exception as e:
                print(f"FAIL   {m}: {e}", file=sys.stderr)
    else:
        if target.suffixes[-2:] == [".meta", ".json"]:
            target = stem_of(target)
        generate(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
