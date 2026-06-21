#!/usr/bin/env python3
"""
Example 2: Search Metatron from Python using the REST API.

Prerequisites:
    pip install httpx
    export METATRON_API_KEY=your-api-key

Usage:
    python examples/search_example.py "what is the Q2 budget?"
"""

import os, sys, json, httpx

API_KEY = os.environ.get("METATRON_API_KEY", "dev-key")
BASE_URL = os.environ.get("METATRON_URL", "http://localhost:8000")


def search(query: str, top_k: int = 5) -> dict:
    """Search Metatron's knowledge base."""
    resp = httpx.post(
        f"{BASE_URL}/api/v1/search",
        json={"query": query, "top_k": top_k},
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def format_results(results: dict) -> None:
    """Pretty-print search results."""
    for i, doc in enumerate(results.get("documents", []), 1):
        title = doc.get("title", "Untitled")
        score = doc.get("score", 0)
        snippet = doc.get("content", "")[:200].replace("\n", " ")
        print(f"\n{i}. {title}  (score: {score:.3f})")
        print(f"   {snippet}...")
        if "source" in doc:
            print(f"   Source: {doc['source']}")


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "what is the Q2 migration status?"
    print(f"🔍 Searching Metatron for: {query}\n")

    try:
        results = search(query)
        total = results.get("total", 0)
        print(f"Found {total} results.")
        format_results(results)
        if total == 0:
            print("\n💡 Tip: Make sure you've synced a data source first.")
            print("   /sync confluence  (from your MCP client)")
            print("   Or: curl -X POST /api/v1/sync/confluence")
    except httpx.ConnectError:
        print("❌ Cannot connect to Metatron.")
        print("   Is 'docker compose up -d' running?")
        print(f"   Checking: {BASE_URL}/ready")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"❌ API error: {e.response.status_code}")
        print(e.response.text)
        sys.exit(1)
