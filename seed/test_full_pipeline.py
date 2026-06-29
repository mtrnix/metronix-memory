#!/usr/bin/env python3
"""End-to-end test of hybrid_search_and_answer on dplat-demo workspace.

Bypasses the auth-gated /api/v1/search endpoint by calling the search function
directly. Prints the LLM answer, primary/supporting source breakdown, and the
trace of pipeline stages so we can see what the demo will actually emit.

Usage:
    python seed/test_full_pipeline.py --workspace dplat-demo
    python seed/test_full_pipeline.py --workspace dplat-demo --query "your question"
    python seed/test_full_pipeline.py --workspace dplat-demo --no-trace
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from metronix.retrieval.search import hybrid_search_and_answer  # noqa: E402

DEFAULT_QUERIES = [
    ("C1  retention", "What is the default retention period for cached connector data?"),
    (
        "Setup Salesforce",
        "How does a workspace admin set up the Salesforce connector for the first time?",
    ),
]


HR = "─" * 90


def print_section(title: str) -> None:
    print(f"\n{HR}\n  {title}\n{HR}")


async def run_one(workspace_id: str, query: str, with_trace: bool) -> None:
    print_section(f"Q: {query}")
    t0 = time.time()
    try:
        result = await hybrid_search_and_answer(
            query=query,
            user_id="seed-test",
            k=25,
            workspace_id=workspace_id,
            return_trace=with_trace,
            source="seed-test",
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return
    elapsed = time.time() - t0

    if isinstance(result, str):
        print(f"\nANSWER ({elapsed:.1f}s):\n")
        print(result)
        return

    # return_trace=True → dict
    answer = result.get("answer", "")
    print(f"\nANSWER ({elapsed:.1f}s):\n")
    print(answer)

    # Trace summary — pipeline stages
    trace = result.get("trace") or {}
    if trace:
        print("\nTRACE summary:")
        for k, v in trace.items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                print(f"  {k}: {v}")
            elif isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
            else:
                print(f"  {k}: {type(v).__name__}")

    # Top sources used
    sources = result.get("sources") or []
    if sources:
        print(f"\nSOURCES ({len(sources)}):")
        for i, s in enumerate(sources[:10], 1):
            if isinstance(s, dict):
                print(f"  {i}. {json.dumps(s, ensure_ascii=False)[:250]}")
            else:
                print(f"  {i}. {s}")


async def main_async(args: argparse.Namespace) -> int:
    queries: list[tuple[str, str]] = (
        [(args.label or "custom", args.query)] if args.query else DEFAULT_QUERIES
    )
    for label, q in queries:
        print(f"\n══════ {label} ══════")
        await run_one(args.workspace, q, with_trace=not args.no_trace)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--query", default=None, help="Custom query (else runs default 2)")
    p.add_argument("--label", default=None)
    p.add_argument("--no-trace", action="store_true", help="Skip return_trace=True")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
