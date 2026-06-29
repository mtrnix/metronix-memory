#!/usr/bin/env python3
"""For a given generated section JSON, list / preview the underlying source files
that were cited in the LLM answer. Lets the demo presenter open the actual Jira
JSON / Confluence Markdown / README in parallel with the generated section to show
"the LLM didn't make this up — here's the source".

Usage:
    python seed/show_sources.py demo-data/generated/admin-guide/section-3_3.json
    python seed/show_sources.py demo-data/generated/admin-guide/section-3_3.json --subsection "Retention Rules"
    python seed/show_sources.py demo-data/generated/marketing/section-F-B1.json --paths-only

Outputs (default):
    For each cited source: doc_label, file path, status (exists / missing), 5-line preview.
    Cross-section dedup — each source listed once with subsections that cited it.
"""  # noqa: E501

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────── source path resolution ─────────────────────────────

JIRA_DIR = REPO_ROOT / "demo-data" / "jira"
CONF_DIR = REPO_ROOT / "demo-data" / "confluence" / "DPLAT"
README_DIR = REPO_ROOT / "demo-data" / "bitbucket"

JIRA_KEY_RE = re.compile(r"\[?(DPLAT-(?:EPIC-|REQ-|DEF-)?\d+)\]?")
CONF_TITLE_RE = re.compile(r"^[A-Z]")  # Confluence titles always start with capital


def resolve_source_path(citation: dict) -> Path | None:
    """Map a citation entry from section JSON → an actual file under demo-data/."""
    icon = citation.get("icon", "")
    title = citation.get("title", "") or ""
    url = citation.get("url", "") or ""

    # Jira: title contains [DPLAT-XXX] OR url contains /browse/DPLAT-...
    jira_key = None
    m = JIRA_KEY_RE.search(title)
    if m:
        jira_key = m.group(1)
    elif "/browse/" in url:
        m2 = re.search(r"/browse/([A-Z][A-Z0-9_-]*)", url)
        if m2:
            jira_key = m2.group(1)
    if jira_key:
        p = JIRA_DIR / f"{jira_key}.json"
        return p if p.exists() else None

    # Bitbucket README: url like https://demo-bitbucket.local/<repo>/blob/main/README.md
    m_rd = re.search(r"demo-bitbucket\.local/([\w-]+)/blob", url)
    if m_rd:
        p = README_DIR / m_rd.group(1) / "README.md"
        return p if p.exists() else None

    # Confluence: url has /wiki/spaces/DPLAT/pages/<page_id> — but our synthetic
    # page_id is a hash of slug; the actual files live in demo-data/confluence/DPLAT/
    # named NN-slug.md. Match by title.
    if icon == "📄" or "demo-confluence" in url:
        # Try filename lookup via title — slugify
        slug_guess = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        for p in CONF_DIR.glob("*.md"):
            if slug_guess in p.stem.lower():
                return p
        # Fallback — return first 5 chars match
        for p in CONF_DIR.glob("*.md"):
            try:
                first_lines = p.read_text()[:500]
                if title and title in first_lines:
                    return p
            except Exception:  # noqa: BLE001
                continue
    return None


# ─────────────────────── output formatting ──────────────────────────────────


def preview(path: Path, n_lines: int = 5) -> str:
    try:
        text = path.read_text()
    except Exception as e:  # noqa: BLE001
        return f"  ⚠ unreadable: {e}"
    if path.suffix == ".json":
        # Show key/summary/status for Jira
        try:
            d = json.loads(text)
            keys = ["key", "issuetype", "status", "priority", "summary"]
            return "  " + "  ".join(f"{k}={d.get(k)!r}" for k in keys if k in d)
        except Exception:  # noqa: BLE001
            pass
    # Default: first n non-empty lines
    lines = [ln for ln in text.split("\n") if ln.strip()][:n_lines]
    return "\n".join("  │ " + ln[:100] for ln in lines)


def render_section(data: dict, only_subsection: str | None, paths_only: bool) -> None:
    sid = data.get("section_id", "?")
    title = data.get("title", "")
    print(f"\n══ section {sid} — {title} ══")
    if data.get("feature"):
        print(f"   feature: {data['feature']}  audience: {', '.join(data.get('audience') or [])}")

    # Aggregate citations across subsections (dedup, track which subs cite each)
    by_path: dict[str, dict] = {}
    unresolved: list[dict] = []
    for sub in data.get("subsections", []) or []:
        sub_title = sub.get("title", "?")
        if only_subsection and sub_title.lower() != only_subsection.lower():
            continue
        for cit in sub.get("sources", []) or []:
            path = resolve_source_path(cit)
            if path is None:
                unresolved.append({"sub": sub_title, **cit})
                continue
            key = str(path)
            if key not in by_path:
                by_path[key] = {
                    "path": path,
                    "title": cit.get("title", ""),
                    "icon": cit.get("icon", ""),
                    "subs": set(),
                }
            by_path[key]["subs"].add(sub_title)

    # Render
    if not by_path and not unresolved:
        print("  (no sources cited)")
        return

    print(f"\n   ┌── {len(by_path)} unique source files cited ──")
    for key in sorted(by_path):
        rec = by_path[key]
        rel = rec["path"].relative_to(REPO_ROOT)
        sub_list = ", ".join(sorted(rec["subs"]))
        print(f"\n   {rec['icon']}  {rec['title']}")
        print(f"      file: {rel}")
        print(f"      cited in subsections: {sub_list}")
        if not paths_only:
            print(preview(rec["path"]))

    if unresolved:
        print(f"\n   ⚠ {len(unresolved)} citations could not be resolved to a file:")
        for u in unresolved[:10]:
            print(
                f"      [{u.get('icon', '?')}] {u.get('title', '?')}  ←  in subsection '{u.get('sub', '?')}'"  # noqa: E501
            )


# ─────────────────────── main ───────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("section_json", help="Path to a section-*.json under demo-data/generated/")
    p.add_argument(
        "--subsection",
        default=None,
        help="Only show sources for one subsection (e.g. 'Prerequisites')",
    )
    p.add_argument(
        "--paths-only",
        action="store_true",
        help="Don't print previews, only file paths (good for piping to xargs)",
    )
    args = p.parse_args()

    section_path = Path(args.section_json)
    if not section_path.is_file():
        print(f"section json not found: {section_path}", file=sys.stderr)
        return 2
    data = json.loads(section_path.read_text())
    render_section(data, args.subsection, args.paths_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
