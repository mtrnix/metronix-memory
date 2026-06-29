#!/usr/bin/env python3
"""
Example 3: Store and retrieve agent memory via the MCP memory tools.

This demonstrates the three memory kinds:
    - fact: durable knowledge, retrieved by relevance (top-K)
    - preference: always injected into agent context
    - pinned: manually pinned, always injected

Prerequisites:
    pip install httpx
    export METRONIX_API_KEY=your-api-key

Usage:
    python examples/memory_example.py
"""

import os

import httpx

API_KEY = os.environ.get("METRONIX_API_KEY", "dev-key")
BASE_URL = os.environ.get("METRONIX_URL", "http://localhost:8000")

headers = {"Authorization": f"Bearer {API_KEY}"}


def store_memory(content: str, kind: str = "fact") -> dict:
    """Store a memory record."""
    resp = httpx.post(
        f"{BASE_URL}/api/v1/memory/records",
        json={"content": content, "kind": kind},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def search_memory(query: str, kind: str = "fact", limit: int = 5) -> dict:
    """Search agent memory."""
    resp = httpx.post(
        f"{BASE_URL}/api/v1/memory/search",
        json={"query": query, "kind": kind, "limit": limit},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    print("🧠 Metronix Agent Memory Example\n")

    # 1. Store a fact
    print("1. Storing a fact...")
    result = store_memory(
        "The Q2 migration project uses PostgreSQL 16 with pgvector.",
        kind="fact",
    )
    print(f"   ✅ Stored: {result.get('id', 'unknown')}")

    # 2. Store a preference (always injected)
    print("2. Storing a preference...")
    result = store_memory(
        "Always use async/await. Never use synchronous HTTP calls.",
        kind="preference",
    )
    print(f"   ✅ Stored: {result.get('id', 'unknown')}")

    # 3. Store a pinned memory
    print("3. Storing a pinned memory...")
    result = store_memory(
        "Production deployment checklist: run tests, check migrations, backup DB.",
        kind="pinned",
    )
    print(f"   ✅ Stored: {result.get('id', 'unknown')}")

    # 4. Search for facts
    print("\n4. Searching for facts about 'Q2 migration'...")
    results = search_memory("Q2 migration")
    for i, mem in enumerate(results.get("records", []), 1):
        print(f"   {i}. [{mem.get('kind', '?')}] {mem.get('content', '')[:120]}")

    print(f"\n{'=' * 50}")
    print("Preferences and pinned are always injected into agent context.")
    print("Facts are retrieved by relevance (top-K).")
    print("The freshness pipeline auto-detects stale facts over time.")
    print(f"{'=' * 50}")
