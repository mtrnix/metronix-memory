#!/usr/bin/env python3
"""Build a one-page Markdown dashboard summarizing all generated demo sections.

Reads section-*.json files under demo-data/generated/{user-guide,admin-guide}/
and emits demo-data/generated/DASHBOARD.md with:
  - per-skeleton table: section id / title / subsections / flag counts / link
  - aggregate flag breakdown across both guides
  - top-N "hottest" sections (most quality flags) for demo drill-down

Usage:
    python seed/build_dashboard.py
    python seed/build_dashboard.py --root demo-data/generated --out demo-data/generated/DASHBOARD.md
"""  # noqa: E501

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def load_sections(skel_dir: Path) -> list[dict]:
    out = []
    for f in sorted(skel_dir.glob("section-*.json")):
        try:
            data = json.loads(f.read_text())
            data["_md_path"] = f.with_suffix(".md").name
            out.append(data)
        except Exception as e:  # noqa: BLE001
            print(f"warn: skipped {f}: {e}")
    return out


def flag_counts(section: dict) -> Counter:
    c: Counter = Counter()
    for sub in section.get("subsections", []) or []:
        for fl in sub.get("flags", []) or []:
            c[fl.get("kind", "?")] += 1
    return c


def fmt_flag_cell(c: Counter) -> str:
    if not c:
        return "✅ clean"
    icons = {
        "conflict": "⚠️",
        "stale": "🕒",
        "missing": "❓",
        "defect-mention": "🐛",
        "low-confidence": "🤔",
    }
    parts = [f"{icons.get(k, '•')} {k}×{v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])]
    return " ".join(parts)


def section_row(skel_name: str, sec: dict) -> str:
    sid = sec.get("section_id", "?")
    title = sec.get("title", "")
    subs = len(sec.get("subsections", []))
    counts = flag_counts(sec)
    flag_str = fmt_flag_cell(counts)
    link = f"./{skel_name}/{sec['_md_path']}"
    return f"| `{sid}` | [{title}]({link}) | {subs} | {flag_str} |"


def aggregate_counts(sections: list[dict]) -> Counter:
    c: Counter = Counter()
    for sec in sections:
        c.update(flag_counts(sec))
    return c


def hottest_sections(
    all_sections: list[tuple[str, dict]], n: int = 5
) -> list[tuple[str, dict, int]]:
    scored = [(skel, sec, sum(flag_counts(sec).values())) for skel, sec in all_sections]
    scored = [(s, sec, total) for s, sec, total in scored if total > 0]
    return sorted(scored, key=lambda t: -t[2])[:n]


def build(root: Path, out_path: Path) -> None:
    skeletons = sorted([d for d in root.iterdir() if d.is_dir() and any(d.glob("section-*.json"))])

    md: list[str] = [
        "# DPLAT Demo — Generated Documentation Dashboard",
        "",
        f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "Auto-built from `demo-data/generated/<skeleton>/section-*.json`. ",
        "Each row links to the rendered Markdown section. Flag legend:",
        "",
        "- ⚠️ **conflict** — sources disagree on a fact (e.g. 30d vs 60d vs 90d retention)",
        "- 🕒 **stale** — answer cites legacy/superseded material",
        "- ❓ **missing** — question not covered by any source",
        "",
        "---",
        "",
    ]

    all_sections: list[tuple[str, dict]] = []
    for skel in skeletons:
        secs = load_sections(skel)
        all_sections.extend((skel.name, s) for s in secs)
        title = skel.name.replace("-", " ").title()
        total_subs = sum(len(s.get("subsections", [])) for s in secs)
        agg = aggregate_counts(secs)
        md += [
            f"## {title}",
            "",
            f"**{len(secs)} sections · {total_subs} subsections · "
            f"flags total: {fmt_flag_cell(agg) if agg else '✅ clean'}**",
            "",
            "| ID | Section | Subs | Flags |",
            "|----|---------|-----:|-------|",
        ]
        md += [section_row(skel.name, s) for s in secs]
        md += ["", ""]

    # Hottest = best demo drill-down candidates
    hot = hottest_sections(all_sections, n=5)
    if hot:
        md += [
            "---",
            "",
            "## Top demo drill-downs (most quality flags)",
            "",
            "| # | Section | Subs | Flags | File |",
            "|---|---------|-----:|-------|------|",
        ]
        for i, (skel, sec, _total) in enumerate(hot, 1):
            counts = flag_counts(sec)
            md.append(
                f"| {i} | **{sec.get('section_id')}** {sec.get('title', '')} "
                f"| {len(sec.get('subsections', []))} | {fmt_flag_cell(counts)} "
                f"| [`{sec['_md_path']}`](./{skel}/{sec['_md_path']}) |"
            )
        md += [""]

    # Aggregate
    grand_total = aggregate_counts([s for _, s in all_sections])
    md += [
        "---",
        "",
        "## Aggregate",
        "",
        f"- Skeletons: **{len(skeletons)}**",
        f"- Sections generated: **{len(all_sections)}**",
        f"- Subsections generated: **{sum(len(s.get('subsections', [])) for _, s in all_sections)}**",  # noqa: E501
        f"- Total flags: **{sum(grand_total.values())}** "
        f"({fmt_flag_cell(grand_total) if grand_total else 'none'})",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md))
    print(f"wrote {out_path}  ({len(all_sections)} sections, {sum(grand_total.values())} flags)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="demo-data/generated")
    p.add_argument("--out", default="demo-data/generated/DASHBOARD.md")
    args = p.parse_args()
    build(Path(args.root), Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
