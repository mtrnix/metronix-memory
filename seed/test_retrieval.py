#!/usr/bin/env python3
"""Quick retrieval sanity check for the synthetic DPLAT dataset.

Bypasses the auth-gated /api/v1/search endpoint by calling recall channels
directly. Confirms that the C1-C6 quality signals are reachable via search.

Usage:
    python seed/test_retrieval.py --workspace dplat-demo
    python seed/test_retrieval.py --workspace dplat-demo --query "your custom question"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from metatron.core.config import Settings  # noqa: E402
from metatron.retrieval.channels import RecallContext, recall_dense_async  # noqa: E402


C1_QUERY = "what is the default retention period for cached connector data?"
C1B_QUERY = "what is the connector recovery SLA after upstream outage?"
C2_QUERY = "how does the PII classifier work? rule-based or ML?"
C3_QUERY = "what is the audit log retention period?"
SETUP_QUERY = "how do I set up the Salesforce connector?"


def _make_ctx(query: str, workspace_id: str) -> RecallContext:
    return RecallContext(
        original_query=query,
        translated_query=query,
        expanded_query=query,
        detected_language="en",
        workspace_id=workspace_id,
        access_filter=None,
        settings=Settings(),
        extracted_jira_keys=[],
        extracted_title_entities=[],
        extracted_dates=None,
        detected_person=[],
        is_activity_query=False,
    )


async def run_query(workspace_id: str, query: str, top_k: int = 8) -> None:
    print(f"\n──── {query} ────")
    ctx = _make_ctx(query, workspace_id)
    try:
        results = await recall_dense_async(ctx)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: {type(e).__name__}: {e}")
        return
    if not results:
        print("  (no results)")
        return
    # results from recall_dense_async are dicts: {channel, chunk_id, doc_label, memory, score}
    # `memory` is the full chunk text starting with "# [<key>] <title>" for jira / "# <title>" for conf
    for i, r in enumerate(results[:top_k], 1):
        score = r.get("score", 0.0)
        doc_label = r.get("doc_label", "?")
        memory = r.get("memory") or {}
        text = memory.get("memory") if isinstance(memory, dict) else str(memory)
        # Extract title: first line of content
        title = ""
        if text:
            first_line = text.lstrip().split("\n", 1)[0]
            title = first_line.lstrip("# ").strip()
        print(f"  {i:>2}. [{score:.3f}] {doc_label:18}  — {title[:80]}")


async def main_async(args: argparse.Namespace) -> int:
    if args.query:
        await run_query(args.workspace, args.query, args.top_k)
        return 0
    queries = {
        "C1  (retention conflict 30/60/90d)":  C1_QUERY,
        "C1b (SLA conflict 30m/60m/4h)":       C1B_QUERY,
        "C2  (PII classifier — staleness)":     C2_QUERY,
        "C3  (audit log retention — missing)":  C3_QUERY,
        "Setup (Salesforce — happy path)":      SETUP_QUERY,
    }
    for label, q in queries.items():
        print(f"\n=== {label} ===")
        await run_query(args.workspace, q, args.top_k)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--query", default=None, help="Custom query (else runs C1/C1b/C2/C3/setup)")
    p.add_argument("--top-k", type=int, default=8)
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
