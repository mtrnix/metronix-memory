#!/usr/bin/env python3
"""PROJ-397 reproducible RAG eval — before/after harness.

Runs a fixed set of queries (three buckets: regression / positive / adversarial) through
the live REST chat endpoint, pulls each RAG debug trace, and prints a structured per-query
summary so a reviewer can diff "before" vs "after" without eyeballing raw traces.

This is the M-4 merge gate for the regression bucket. It needs a live stand (Postgres /
Qdrant / Neo4j) and trace capture enabled (METRONIX_RAG_TRACE_ENABLED=true). It is NOT a
unit test — run it manually:

    python scripts/rag_eval_397.py \
        --base-url http://localhost:8000 \
        --email "$METRONIX_ADMIN_EMAIL" --password "$METRONIX_ADMIN_PASSWORD" \
        --workspace MTRNIX --out before.json

Re-run after each phase with --out after.json, then diff the two JSON files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from typing import Any

# Query buckets -------------------------------------------------------------

REGRESSION = [
    "what are next weeks tasks",
    "Check jira sprint for week 22",
    "Use jira mtrnix and GitHub to show next week activity",
    "what type of model do you use? how many parameters?",  # must NOT regress
]
POSITIVE = [
    "what is PROJ-281 about",
    "summarize the 2026-05-08 daily summary",
    "who works on the freshness pipeline",
    "what was done for memory health",
]
ADVERSARIAL = [
    "what are the tasks for the week of 2027-01-04",  # future, no data → must not fabricate
    "extract the link from https://example.com/auth?code=abc",  # non-RAG
    "что в спринте на следующей неделе и кто над чем работает",  # cross-language, multi-intent
    "tell me about the Atlantis migration project",  # likely absent → must say "not found"
]

_TRACE_RE = re.compile(r"trace:\s*([0-9a-f-]{36})", re.IGNORECASE)
_TICKET_RE = re.compile(r"\b[A-Z]{2,}-\d+\b")


def _post(url: str, body: dict, token: str | None = None, timeout: int = 180) -> dict:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _get(url: str, token: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _login(base: str, email: str, password: str) -> str:
    out = _post(f"{base}/api/v1/auth/login", {"email": email, "password": password})
    return out["token"]


def _phase(trace: dict, name: str) -> dict | None:
    for p in trace.get("phases", []):
        if p.get("name") == name:
            return p
    return None


def _summarize_trace(trace: dict, answer: str) -> dict[str, Any]:
    recall = _phase(trace, "recall") or {}
    channels = recall.get("channels", {})
    chan_counts = {
        c: (ch.get("count") if isinstance(ch, dict) else len(ch)) for c, ch in channels.items()
    }
    merge = _phase(trace, "merge_and_score") or {}
    cands = merge.get("candidates", [])
    titles = Counter((c.get("title") or "")[:40] for c in cands)
    dups = sum(n - 1 for n in titles.values() if n > 1)
    rerank = _phase(trace, "rerank") or {}
    rc = sorted(rerank.get("candidates", []), key=lambda x: x.get("final_score", 0), reverse=True)
    top5 = [(c.get("source"), (c.get("title") or "")[:40]) for c in rc[:5]]
    gen = _phase(trace, "generation") or {}
    classify = _phase(trace, "classify") or {}
    # Tickets cited in the answer (for the negative bucket's no-hallucination check).
    cited = sorted(set(_TICKET_RE.findall(answer)))
    return {
        "profile": (classify.get("output") or {}).get("profile"),
        "channels": chan_counts,
        "dup_candidates": dups,
        "src_dist": dict(Counter(c.get("source") for c in cands)),
        "rerank_top5": top5,
        "ungrounded_tickets": gen.get("ungrounded_tickets"),
        "cited_tickets": cited,
        "answer_head": answer[:200],
    }


def run_bucket(base: str, token: str, workspace: str, name: str, queries: list[str]) -> list:
    rows = []
    for q in queries:
        try:
            body = {"message": q, "workspace_id": workspace}
            resp = _post(f"{base}/api/v1/chat", body, token=token)
            answer = resp.get("answer") or resp.get("response") or json.dumps(resp)[:200]
            m = _TRACE_RE.search(answer)
            summary: dict[str, Any] = {"query": q}
            if m:
                trace = _get(f"{base}/api/v1/traces/{m.group(1)}", token)
                summary.update(_summarize_trace(trace, answer))
                summary["trace_id"] = m.group(1)
            else:
                summary["error"] = "no trace footer in answer"
                summary["answer_head"] = answer[:200]
            rows.append(summary)
            print(
                f"[{name}] {q[:50]:50}  profile={summary.get('profile')}  "
                f"channels={summary.get('channels')}"
            )
        except Exception as e:  # noqa: BLE001 — eval harness, report and continue
            rows.append({"query": q, "error": str(e)})
            print(f"[{name}] {q[:50]:50}  ERROR {e}")
        time.sleep(1)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="PROJ-397 RAG eval harness")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--workspace", default="MTRNIX")
    ap.add_argument("--out", default="rag_eval_397.json")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    token = _login(base, args.email, args.password)
    result = {
        "regression": run_bucket(base, token, args.workspace, "regression", REGRESSION),
        "positive": run_bucket(base, token, args.workspace, "positive", POSITIVE),
        "adversarial": run_bucket(base, token, args.workspace, "adversarial", ADVERSARIAL),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {args.out}. Diff before/after JSON to evaluate the change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
