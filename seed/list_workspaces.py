#!/usr/bin/env python3
"""List all workspaces in this Metatron instance, bypassing the auth-gated API.

Goes straight through WorkspaceManager (loads from PG/Neo4j via the in-memory
manager). Run from the metatroncore repo root.

Usage:
    python seed/list_workspaces.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from metatron.workspaces.manager import get_workspace_manager  # noqa: E402


def main() -> int:
    mgr = get_workspace_manager()
    wss = mgr.list_workspaces()
    if not wss:
        print("(no workspaces)")
        return 0
    print(f"{'workspace_id':24}  {'name':40}  user")
    print("-" * 80)
    for w in wss:
        print(f"{w.workspace_id:24}  {(w.name or ''):40}  {getattr(w, 'user_id', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
