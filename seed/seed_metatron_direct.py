#!/usr/bin/env python3
"""Direct Metatron ingestion (Path B from docs/superpowers/2026-05-02-amisol-demo-plan.md §8.2).

Reads demo-data/ and pushes Documents straight into the ingestion pipeline,
bypassing Atlassian APIs. Payloads mirror exactly what jira/confluence connectors
emit, so retrieval treats synthetic and real data identically.

Usage:
    python seed/seed_metatron_direct.py --workspace demo
    python seed/seed_metatron_direct.py --workspace demo --only jira
    python seed/seed_metatron_direct.py --workspace demo --dry-run
    python seed/seed_metatron_direct.py --workspace demo --skip-graph

Run from the metatroncore repo root. Uses the project's own venv / deps.
PostgreSQL + Qdrant must be up. Neo4j only needed without --skip-graph.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from metatron.core.models import Document  # noqa: E402
from metatron.ingestion.pipeline import ingest_documents  # noqa: E402
from metatron.workspaces.manager import get_workspace_manager  # noqa: E402

JIRA_BASE_URL = "https://demo-jira.local"
CONF_BASE_URL = "https://demo-confluence.local"
GH_BASE_URL = "https://demo-bitbucket.local"
DPLAT_SPACE = "DPLAT"

# DEMO-ONLY: when --github-urls is passed, sources cite the public GitHub
# blob URL of the underlying synthetic file instead of the fake demo-*.local
# host. This makes the citation links in OpenWebUI clickable during the live
# demo (clicking opens the actual JSON / MD file rendered by GitHub).
# Override via env GITHUB_DEMO_BASE if the repo or branch differs.
GITHUB_DEMO_BASE = os.environ.get(
    "GITHUB_DEMO_BASE",
    "https://github.com/mtrnix/metatroncore/blob/develop/demo-data",
)


# ─────────────────────── Markdown rendering for retrieval ───────────────────

def render_jira_markdown(issue: dict) -> str:
    """Render our internal Jira JSON as Markdown for indexing.

    Mirrors the shape that `jira_processing.jira_issue_to_markdown` emits on the
    real connector path so retrieval scores synthetic and real Jira identically.
    """
    parts: list[str] = [
        f"# [{issue['key']}] {issue['summary']}",
        "",
        f"**Type:** {issue['issuetype']}  ",
        f"**Status:** {issue.get('status', '')}  ",
        f"**Priority:** {issue.get('priority', '')}  ",
        f"**Reporter:** {issue.get('reporter', '')}  ",
        f"**Assignee:** {issue.get('assignee', '')}  ",
        f"**Labels:** {', '.join(issue.get('labels', []))}  ",
        f"**Components:** {', '.join(issue.get('components', []))}  ",
        f"**Fix versions:** {', '.join(issue.get('fix_versions', []))}",
    ]
    if issue.get("epic_link"):
        parts.append(f"**Epic:** {issue['epic_link']}")
    if issue.get("linked_issues"):
        parts.append("\n**Linked issues:**")
        for li in issue["linked_issues"]:
            parts.append(f"- {li.get('type', 'relates')} → {li.get('key', '')}")
    if issue.get("linked_confluence"):
        parts.append("\n**Linked Confluence:**")
        for lc in issue["linked_confluence"]:
            parts.append(f"- {lc.get('space', '')}/{lc.get('slug', '')}")
    parts += ["", "## Description", "", issue.get("description_md", "")]
    if issue.get("comments"):
        parts.append("\n## Comments")
        for c in issue["comments"]:
            parts.append(f"\n### {c.get('author', '')} — {c.get('created', '')}")
            parts.append("")
            parts.append(c.get("body_md", ""))
    return "\n".join(parts)


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ─────────────────────── Document constructors ─────────────────────────────

def jira_document(issue: dict, workspace_id: str, github_urls: bool = False) -> Document:
    key = issue["key"]
    url = (
        f"{GITHUB_DEMO_BASE}/jira/{key}.json"
        if github_urls
        else f"{JIRA_BASE_URL}/browse/{key}"
    )
    return Document(
        source_type="jira",
        source_id=key,
        url=url,
        workspace_id=workspace_id,
        title=f"[{key}] {issue.get('summary', '')}",
        content=render_jira_markdown(issue),
        author=issue.get("reporter") or "",
        tags=list(issue.get("labels", [])),
        source_role="task_tracker",
        metadata={
            "issue_key": key,
            "status": issue.get("status", "") or "",
            "assignee": issue.get("assignee") or "",
            "reporter": issue.get("reporter") or "",
            "issuetype": issue.get("issuetype") or "",
            "priority": issue.get("priority") or "",
            "type": "jira",
            "epic_link": issue.get("epic_link") or "",
            "created_at_str": issue.get("created") or "",
            "updated_at_str": issue.get("updated") or "",
            "resolved_at_str": issue.get("resolved") or "",
        },
        created_at=parse_iso(issue.get("created")) or datetime.utcnow(),
        updated_at=parse_iso(issue.get("updated")) or datetime.utcnow(),
    )


def parse_confluence_md(text: str) -> tuple[dict, str]:
    """Split Confluence MD: YAML frontmatter + body."""
    if not text.lstrip().startswith("---"):
        raise ValueError("file does not start with frontmatter '---'")
    after_first = text.split("---", 2)
    if len(after_first) < 3:
        raise ValueError("malformed frontmatter (no closing '---')")
    fm = yaml.safe_load(after_first[1]) or {}
    body = after_first[2].lstrip("\n")
    return fm, body


def confluence_document(
    fm: dict, body: str, workspace_id: str, github_urls: bool = False
) -> Document:
    space = fm.get("space", DPLAT_SPACE)
    slug = fm["slug"]
    page_id = hashlib.md5(f"{space}/{slug}".encode()).hexdigest()[:12]
    url = (
        f"{GITHUB_DEMO_BASE}/confluence/{space}/{slug}.md"
        if github_urls
        else f"{CONF_BASE_URL}/wiki/spaces/{space}/pages/{page_id}"
    )
    return Document(
        source_type="confluence",
        source_id=page_id,
        workspace_id=workspace_id,
        title=fm.get("title", slug),
        content=body,
        url=url,
        author=str(fm.get("author", "") or ""),
        tags=list(fm.get("labels", []) or []),
        source_role="knowledge_base",
        metadata={
            "space_key": space,
            "page_id": page_id,
            "slug": slug,
            "last_modified": str(fm.get("updated", "") or ""),
            "author": str(fm.get("author", "") or ""),
            "type": "confluence",
            "status": str(fm.get("status", "current") or "current"),
            "version": str(fm.get("version", 1)),
            "linked_jira": ",".join(fm.get("linked_jira", []) or []),
            "parent_slug": str(fm.get("parent_slug", "") or ""),
        },
        created_at=parse_iso(str(fm.get("created", ""))) or datetime.utcnow(),
        updated_at=parse_iso(str(fm.get("updated", ""))) or datetime.utcnow(),
    )


def readme_document(
    repo: str, body: str, workspace_id: str, github_urls: bool = False
) -> Document:
    url = (
        f"{GITHUB_DEMO_BASE}/bitbucket/{repo}/README.md"
        if github_urls
        else f"{GH_BASE_URL}/{repo}/blob/main/README.md"
    )
    return Document(
        source_type="github",
        source_id=f"readme:{repo}",
        workspace_id=workspace_id,
        title=f"{repo} — README",
        content=body,
        url=url,
        author="",
        tags=[f"repo:{repo}", "doc-type:readme"],
        source_role="knowledge_base",
        metadata={"repo": repo, "type": "github", "path": "README.md"},
    )


# ─────────────────────── Collection + cross-ref check ──────────────────────

def collect(
    root: Path, workspace_id: str, kinds: set[str], github_urls: bool = False
) -> tuple[list[Document], dict]:
    docs: list[Document] = []
    raw_jira: dict[str, dict] = {}
    raw_conf_slugs: set[str] = set()
    skipped: list[tuple[str, str]] = []

    if "jira" in kinds:
        for f in sorted((root / "jira").glob("*.json")):
            try:
                issue = json.loads(f.read_text())
                raw_jira[issue["key"]] = issue
                docs.append(jira_document(issue, workspace_id, github_urls=github_urls))
            except Exception as e:  # noqa: BLE001
                skipped.append((str(f), repr(e)))

    if "confluence" in kinds:
        for f in sorted((root / "confluence" / DPLAT_SPACE).glob("*.md")):
            try:
                fm, body = parse_confluence_md(f.read_text())
                raw_conf_slugs.add(fm["slug"])
                docs.append(confluence_document(fm, body, workspace_id, github_urls=github_urls))
            except Exception as e:  # noqa: BLE001
                skipped.append((str(f), repr(e)))

    if "readme" in kinds:
        for f in sorted((root / "bitbucket").rglob("README.md")):
            try:
                docs.append(
                    readme_document(f.parent.name, f.read_text(), workspace_id,
                                    github_urls=github_urls)
                )
            except Exception as e:  # noqa: BLE001
                skipped.append((str(f), repr(e)))

    info = {"raw_jira": raw_jira, "raw_conf_slugs": raw_conf_slugs, "skipped": skipped}
    return docs, info


def cross_ref_check(info: dict) -> list[str]:
    """Validate that linked_issues / linked_confluence refer to existing artifacts."""
    errors: list[str] = []
    keys = set(info["raw_jira"].keys())
    slugs = info["raw_conf_slugs"]
    for key, issue in info["raw_jira"].items():
        for li in issue.get("linked_issues", []) or []:
            if li.get("key") not in keys:
                errors.append(f"{key} → linked_issue {li.get('key')} (not found)")
        for lc in issue.get("linked_confluence", []) or []:
            if lc.get("slug") not in slugs:
                errors.append(f"{key} → linked_confluence {lc.get('slug')} (not found)")
    return errors


# ─────────────────────── Workspace bootstrap ──────────────────────────────

def ensure_workspace(workspace_id: str, name: str | None, description: str | None) -> str:
    """Create the workspace if it doesn't exist. Idempotent.

    Returns the workspace_id actually used (after normalization by the manager).
    """
    mgr = get_workspace_manager()
    existing = mgr.get_workspace(workspace_id)
    if existing is not None:
        print(f"Workspace '{workspace_id}' already exists — using it.")
        return existing.workspace_id
    ws = mgr.create_workspace(
        name=name or f"DPLAT demo ({workspace_id})",
        description=description or "Synthetic Amisol DataPlatform demo dataset (Path B).",
        user_id="seed-script",
        workspace_id=workspace_id,
    )
    print(f"Workspace '{ws.workspace_id}' created (name={ws.name!r}).")
    return ws.workspace_id


# ─────────────────────── Main ──────────────────────────────────────────────

async def main_async(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_dir():
        print(f"demo-data root not found: {root}", file=sys.stderr)
        return 2

    if not args.dry_run and args.create_workspace:
        try:
            ws_id = ensure_workspace(args.workspace, args.workspace_name, args.workspace_description)
            args.workspace = ws_id
        except Exception as e:  # noqa: BLE001
            print(f"ensure_workspace failed: {e}", file=sys.stderr)
            return 3

    kinds = set(args.only) if args.only else {"jira", "confluence", "readme"}
    docs, info = collect(root, args.workspace, kinds, github_urls=args.github_urls)
    if args.github_urls:
        print(f"  (using GitHub URLs for source citations: {GITHUB_DEMO_BASE})")

    by_type: dict[str, int] = {}
    for d in docs:
        by_type[d.source_type] = by_type.get(d.source_type, 0) + 1
    print(f"Collected {len(docs)} documents:")
    for st, n in sorted(by_type.items()):
        print(f"  {st:12s} {n}")
    if info["skipped"]:
        print(f"\nSKIPPED {len(info['skipped'])} files:", file=sys.stderr)
        for path, err in info["skipped"]:
            print(f"  {path}: {err}", file=sys.stderr)

    errors = cross_ref_check(info)
    if errors:
        print(f"\nWARN: {len(errors)} broken cross-references:", file=sys.stderr)
        for e in errors[:25]:
            print(f"  {e}", file=sys.stderr)
        if len(errors) > 25:
            print(f"  ... and {len(errors) - 25} more", file=sys.stderr)
    else:
        print("\nCross-references: OK")

    if args.dry_run:
        print("\n--dry-run: not ingesting. Done.")
        return 0

    # Ingest in source_type batches so per-batch logs make sense.
    for st in ["jira", "confluence", "github"]:
        batch = [d for d in docs if d.source_type == st]
        if not batch:
            continue
        print(f"\nIngesting {len(batch)} {st} documents into workspace={args.workspace}...")
        result = await ingest_documents(
            documents=batch,
            workspace_id=args.workspace,
            connector_type=st,
            incremental=False,
            skip_graph=args.skip_graph,
        )
        print(
            f"  documents_new={result.documents_new}  "
            f"documents_updated={result.documents_updated}  "
            f"documents_skipped={result.documents_skipped}  "
            f"errors={len(result.errors)}  "
            f"duration_ms={result.duration_ms:.0f}"
        )
        if result.errors:
            for err in result.errors[:5]:
                print(f"    ! {err}", file=sys.stderr)

    print(f"\nDone. Workspace: {args.workspace}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Seed Metatron with synthetic DPLAT demo data.")
    p.add_argument("--workspace", required=True, help="Target workspace_id")
    p.add_argument("--root", default="demo-data", help="Path to demo-data root (default: demo-data)")
    p.add_argument(
        "--only", choices=["jira", "confluence", "readme"], action="append",
        default=None, help="Limit to specific kinds (repeatable)",
    )
    p.add_argument("--dry-run", action="store_true", help="Collect, validate, do not ingest")
    p.add_argument("--skip-graph", action="store_true", help="Skip Neo4j graph extraction (faster)")
    p.add_argument(
        "--create-workspace", action="store_true",
        help="Create the workspace if it doesn't exist (idempotent)",
    )
    p.add_argument("--workspace-name", default=None, help="Display name for created workspace")
    p.add_argument("--workspace-description", default=None, help="Description for created workspace")
    p.add_argument(
        "--github-urls", action="store_true",
        help="DEMO-ONLY: emit clickable GitHub blob URLs in citations instead of "
             "demo-{jira,confluence,bitbucket}.local. Override base via env GITHUB_DEMO_BASE.",
    )
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
