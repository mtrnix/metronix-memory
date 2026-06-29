#!/usr/bin/env python3
"""DEMO-ONLY: build a Markdown index of all synthetic source artifacts.

Reads `demo-data/{jira,confluence/DPLAT,bitbucket}/` and emits a single
Markdown index file (`demo-data/generated/SOURCES_INDEX.md`) that:
  - groups every artifact by type (epics / stories / requirements / defects /
    confluence pages / READMEs)
  - tags artifacts that participate in quality signals C1, C1b, C2, C2b, C3, C4, C6
  - links to the actual file (relative path — opens nicely in GitHub web UI,
    in IDEs, and in any Markdown viewer that resolves relative links)

Used during the Amisol demo to let the audience see the underlying data —
"the LLM didn't make this up; here's the source file."

This script and the file it emits are demo-only. After the demo is over,
both can be deleted without touching production code.

Usage:
    python seed/build_sources_index.py
    python seed/build_sources_index.py --root demo-data \
                                       --out demo-data/generated/SOURCES_INDEX.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

# DEMO: which artifacts participate in which signal — matches §4.5 / §C1b / §C2b
# of the master plan. Used to badge rows in the index so the demo presenter
# can find the conflict / staleness epicentres in one click.
QUALITY_SIGNAL_BADGES: dict[str, list[str]] = {
    # C1 retention conflict (30 / 60 / 90 days)
    "DPLAT-DEF-04": ["C1 conflict (90d)"],
    "DPLAT-006": ["C1 conflict (60d)"],
    "conf-04": ["C1 source-of-truth (30d)"],
    "conf-05": ["C1 platform policy (30d)"],
    # C1b SLA conflict (30 min / 60 min / 4h)
    "DPLAT-030": ["C1b conflict (60m)"],
    "DPLAT-DEF-15": ["C1b conflict (4h)"],
    "DPLAT-REQ-15": ["C1b conflict (30m)"],
    "conf-15": ["C1b runbook (30m)"],
    # C2 staleness — PII initial design legacy
    "conf-09": ["C2 stale (legacy 2024)"],
    "DPLAT-005": ["C2 supersedes conf-09"],
    # C2b staleness — Audit Log v1 legacy
    "conf-19": ["C2b stale (legacy 2024)"],
    "DPLAT-029": ["C2b supersedes conf-19"],
    # C4 cross-source linking
    "DPLAT-002": ["C4 cross-link"],
    "DPLAT-DEF-02": ["C4 cross-link"],
    # C6 defect-not-behavior
    "DPLAT-DEF-07": ["C6 defect ≠ behavior"],
}


# ─────────────────────── helpers ────────────────────────────────────────────


def jira_kind(key: str) -> str:
    if "-EPIC-" in key:
        return "Epics"
    if "-REQ-" in key:
        return "Requirements"
    if "-DEF-" in key:
        return "Defects (Bugs)"
    return "User Stories"


def render_badges(badges: list[str]) -> str:
    if not badges:
        return ""
    return " ".join(f"`{b}`" for b in badges)


def confluence_slug_id(filename: str) -> str:
    """Map demo-data filename '04-foo-bar.md' → 'conf-04' for badge lookup."""
    m = re.match(r"^(\d+)-", filename)
    if m:
        return f"conf-{m.group(1).zfill(2)}"
    return ""


# ─────────────────────── readers ────────────────────────────────────────────


def read_jira_inventory(root: Path) -> list[dict]:
    items: list[dict] = []
    for f in sorted((root / "jira").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        items.append(
            {
                "key": d.get("key", f.stem),
                "type": d.get("issuetype", "?"),
                "summary": d.get("summary", ""),
                "status": d.get("status", ""),
                "priority": d.get("priority", ""),
                "labels": d.get("labels", []),
                "epic_link": d.get("epic_link"),
                "path": f.relative_to(root.parent),
            }
        )
    return items


def read_confluence_inventory(root: Path) -> list[dict]:
    items: list[dict] = []
    for f in sorted((root / "confluence" / "DPLAT").glob("*.md")):
        text = f.read_text()
        title = ""
        slug = f.stem
        status = "current"
        m = re.search(r'^title:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
        if m:
            title = m.group(1).strip().strip('"')
        m = re.search(r"^slug:\s*(.+?)\s*$", text, re.MULTILINE)
        if m:
            slug = m.group(1).strip()
        m = re.search(r"^status:\s*(.+?)\s*$", text, re.MULTILINE)
        if m:
            status = m.group(1).strip()
        items.append(
            {
                "slug": slug,
                "title": title,
                "status": status,
                "path": f.relative_to(root.parent),
                "badge_id": confluence_slug_id(f.name),
            }
        )
    return items


def read_readme_inventory(root: Path) -> list[dict]:
    items: list[dict] = []
    for f in sorted((root / "bitbucket").rglob("README.md")):
        repo = f.parent.name
        items.append(
            {
                "repo": repo,
                "path": f.relative_to(root.parent),
            }
        )
    return items


# ─────────────────────── render ─────────────────────────────────────────────


def render(jira: list[dict], conf: list[dict], readmes: list[dict]) -> str:
    lines: list[str] = [
        "# DPLAT Demo — Source Artifacts Index",
        "",
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · "
        "demo-only, will be removed after the Amisol demo._",
        "",
        "Every entry below is one synthetic artifact that was ingested into the "
        "`dplat-demo` workspace. Links open the underlying file (rendered nicely "
        "by GitHub for `.json` and `.md`).",
        "",
        "Quality-signal badges flag artifacts that participate in a deliberate "
        "demo moment — pick any with **C1 / C1b / C2 / C2b / C4 / C6** to drill "
        "into the headline scenes.",
        "",
        "---",
        "",
    ]

    # ── Jira, grouped by kind ──
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for it in jira:
        by_kind[jira_kind(it["key"])].append(it)

    lines.append(f"## Jira ({len(jira)} artifacts)")
    lines.append("")
    for kind in ["Epics", "User Stories", "Requirements", "Defects (Bugs)"]:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.append(f"### {kind} ({len(items)})")
        lines.append("")
        lines.append("| Key | Type | Status | Summary | Signal |")
        lines.append("|-----|------|--------|---------|--------|")
        for it in items:
            badges = QUALITY_SIGNAL_BADGES.get(it["key"], [])
            link = f"[`{it['key']}`](../../{it['path']})"
            summary = it["summary"][:90].replace("|", "\\|")
            lines.append(
                f"| {link} | {it['type']} | {it['status']} | {summary} | {render_badges(badges)} |"
            )
        lines.append("")

    # ── Confluence ──
    lines.append(f"## Confluence ({len(conf)} pages)")
    lines.append("")
    lines.append("| Page | Status | Title | Signal |")
    lines.append("|------|--------|-------|--------|")
    for it in conf:
        badges = QUALITY_SIGNAL_BADGES.get(it["badge_id"], [])
        link = f"[`{it['slug']}`](../../{it['path']})"
        title = (it["title"] or it["slug"])[:80].replace("|", "\\|")
        status_str = it["status"]
        if status_str == "superseded":
            status_str = f"🕒 **{status_str}**"
        elif status_str == "draft":
            status_str = f"_{status_str}_"
        lines.append(f"| {link} | {status_str} | {title} | {render_badges(badges)} |")
    lines.append("")

    # ── READMEs ──
    lines.append(f"## Bitbucket READMEs ({len(readmes)} repos)")
    lines.append("")
    lines.append("| Repo | File |")
    lines.append("|------|------|")
    for it in readmes:
        lines.append(f"| `{it['repo']}` | [README.md](../../{it['path']}) |")
    lines.append("")

    # ── Quality-signal index for fast drill-down on demo ──
    lines += [
        "---",
        "",
        "## Quality-signal index (demo drill-down)",
        "",
        "Open any of the artifacts below to find the source-text behind a demo moment.",
        "",
    ]
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for art_id, badges in QUALITY_SIGNAL_BADGES.items():
        for b in badges:
            sig = b.split()[0]
            grouped[sig].append((art_id, b))
    for sig in sorted(grouped):
        signal_label = {
            "C1": "C1 — retention conflict (30d / 60d / 90d)",
            "C1b": "C1b — connector recovery SLA conflict (30m / 60m / 4h)",
            "C2": "C2 — PII classifier staleness (legacy 2024 → current)",
            "C2b": "C2b — Audit Log v1 staleness (legacy 2024 → current)",
            "C4": "C4 — cross-source linking (DPLAT-002 ↔ conf-04 ↔ DPLAT-DEF-02)",
            "C6": "C6 — defect-not-behavior (DPLAT-DEF-07 must NOT propagate to user guide)",
        }.get(sig, sig)
        lines.append(f"### {signal_label}")
        lines.append("")
        for art_id, badge in grouped[sig]:
            lines.append(f"- `{art_id}` — {badge}")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────── main ───────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="demo-data")
    p.add_argument("--out", default="demo-data/generated/SOURCES_INDEX.md")
    args = p.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"demo-data root not found: {root}")
        return 2

    jira = read_jira_inventory(root)
    conf = read_confluence_inventory(root)
    readmes = read_readme_inventory(root)
    md = render(jira, conf, readmes)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)
    print(f"wrote {out_path}")
    print(f"  jira:       {len(jira)} (epics/stories/reqs/defects)")
    print(f"  confluence: {len(conf)} pages")
    print(f"  readmes:    {len(readmes)} repos")
    badged = sum(1 for k in QUALITY_SIGNAL_BADGES)
    print(f"  badges:     {badged} artifacts tagged across C1/C1b/C2/C2b/C4/C6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
