#!/usr/bin/env python3
"""Doc-generator agent — fills a documentation skeleton from a Metatron index.

Walks a YAML skeleton (`demo-data/skeletons/*.yaml`), and for every leaf section
runs Metatron's hybrid_search_and_answer pipeline once per `sections_required`
subsection. Aggregates results into a structured JSON page (per §10.2 of
docs/superpowers/2026-05-02-amisol-demo-plan.md) and renders Markdown.

Usage:
    python seed/doc_generator.py --workspace dplat-demo --skeleton demo-data/skeletons/user-guide.yaml
    python seed/doc_generator.py --workspace dplat-demo --skeleton .../user-guide.yaml --section 2.1
    python seed/doc_generator.py --workspace dplat-demo --skeleton .../user-guide.yaml --section 2.1 --out demo-data/generated/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    import yaml
except ImportError:
    print("ERROR: pip install pyyaml", file=sys.stderr); sys.exit(1)

from metatron.retrieval.search import hybrid_search_and_answer  # noqa: E402


# Heuristic flag patterns — LLM tends to use these phrasings naturally.
FLAG_PATTERNS = {
    "conflict": re.compile(
        r"\b(not consistent|conflict\w*|contradict\w*|discrepanc\w*|"
        r"inconsisten\w*|differ\w* values|three different|"
        r"sources (?:disagree|don'?t agree))\b",
        re.IGNORECASE,
    ),
    "stale":   re.compile(r"\b(superseded|deprecat\w*|legacy|outdated)\b", re.IGNORECASE),
    "missing": re.compile(
        r"\b(no (?:source|information|data) (?:available|covers|provided|found)|"
        r"insufficient information|cannot be determined|not (?:specified|documented)|"
        r"not (?:cover\w*|address\w*) (?:by|in) (?:the )?sources)\b",
        re.IGNORECASE,
    ),
}

SOURCES_HEADER_RE = re.compile(r"^\s*📚\s*Sources:?\s*$", re.MULTILINE)
SOURCE_LINE_RE = re.compile(
    r"^\s*(?P<icon>[📄📋📎📓📊])\s+(?P<title>.+?)\s+—\s+(?P<url>https?://\S+)\s*$",
    re.MULTILINE,
)


@dataclass
class SubsectionResult:
    title: str
    query: str
    body_md: str
    sources: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str | None = None


@dataclass
class SectionResult:
    section_id: str
    title: str
    feature: str | None
    audience: list[str]
    subsections: list[SubsectionResult] = field(default_factory=list)
    generated_at: str = ""


# ─────────────────────── skeleton walking ────────────────────────────────

def iter_leaf_sections(node: dict, path: tuple[str, ...] = (), audience: list[str] | None = None):
    """Yield (section_dict, full_id) for every leaf section in a skeleton."""
    audience = node.get("audience", audience or [])
    for sec in node.get("sections", []) or []:
        yield from _walk(sec, audience)


def _walk(sec: dict, audience: list[str]):
    sid = str(sec.get("id", "?"))
    children = sec.get("children") or []
    if children:
        for child in children:
            yield from _walk(child, audience)
    else:
        sec_with_audience = dict(sec)
        sec_with_audience["__audience"] = audience
        yield sec_with_audience, sid


# ─────────────────────── pipeline call ──────────────────────────────────

def parse_sources_block(answer: str) -> tuple[str, list[dict]]:
    """Split LLM answer into body + parsed sources list."""
    m = SOURCES_HEADER_RE.search(answer)
    if not m:
        return answer.strip(), []
    body = answer[: m.start()].rstrip()
    sources_text = answer[m.end() :]
    sources: list[dict] = []
    for sm in SOURCE_LINE_RE.finditer(sources_text):
        sources.append({
            "icon":  sm.group("icon"),
            "title": sm.group("title").strip(),
            "url":   sm.group("url").strip(),
        })
    return body, sources


def strip_leading_heading(body: str) -> str:
    """LLM often opens with its own H2 mirroring the subsection title.
    The wrapper already prints the canonical H2, so drop the LLM's leading heading
    to avoid `## Prerequisites` followed by `## Prerequisites for Setting Up...`."""
    body = body.lstrip()
    if body.startswith("##"):
        # remove only the first heading line
        first_nl = body.find("\n")
        if first_nl > 0:
            body = body[first_nl + 1 :].lstrip()
    return body


def detect_flags(body: str) -> list[dict]:
    flags: list[dict] = []
    for kind, pat in FLAG_PATTERNS.items():
        m = pat.search(body)
        if m:
            flags.append({
                "kind": kind,
                "evidence": body[max(0, m.start() - 40): m.end() + 40].strip(),
            })
    return flags


def compose_query(section: dict, subsection_title: str) -> str:
    """Build a focused retrieval query: section context + subsection aspect.

    The skeleton's retrieval.filters (labels_any / labels_none / roles) can't yet
    be enforced as Qdrant payload filters because connector-emitted Document.tags
    are not propagated into chunk payload (architectural follow-up). Until that
    lands, we project the same intent into the LLM prompt as natural-language
    constraints. The LLM is good enough to honor them given the section context.
    """
    retrieval = section.get("retrieval", {}) or {}
    base_questions = retrieval.get("questions") or []
    filters = retrieval.get("filters", {}) or {}
    feature = section.get("feature")
    section_title = section.get("title", "")
    audience = section.get("__audience") or []

    parts = [
        f"For the section '{section_title}'" + (f" (feature {feature})" if feature else ""),
        f"answer the following so that it serves the subsection '{subsection_title}':",
    ]
    if base_questions:
        parts.append("Primary question: " + base_questions[0])
        if len(base_questions) > 1:
            parts.append("Related: " + "; ".join(base_questions[1:3]))

    # Audience- and behavior-aware constraints (prompt-level filter, until tags propagate)
    constraints: list[str] = []
    labels_none = filters.get("labels_none") or []
    if "behavior:defect" in labels_none:
        constraints.append(
            "STRICTLY EXCLUDE defect tickets (DPLAT-DEF-*) when describing intended behavior. "
            "Defects describe broken behavior, not specifications. Only mention them under "
            "'known issues' or 'troubleshooting' sub-sections, never as how the feature works."
        )
    roles = filters.get("roles") or []
    if roles and "compliance-officer" not in roles and "workspace-admin" not in roles:
        constraints.append(
            "Tailor the answer for end-users only — avoid admin-only configuration knobs, "
            "permissions matrices, or audit/compliance internals."
        )
    if audience:
        constraints.append(f"Target audience: {', '.join(audience)}.")
    parts.extend(constraints)

    parts.append(f"Focus the answer specifically on the '{subsection_title}' aspect.")
    return " ".join(parts)


async def fill_subsection(
    workspace_id: str, section: dict, subsection_title: str, top_k: int
) -> SubsectionResult:
    query = compose_query(section, subsection_title)
    t0 = time.time()
    try:
        answer = await hybrid_search_and_answer(
            query=query,
            user_id="doc-generator",
            k=top_k,
            workspace_id=workspace_id,
            return_trace=False,
            source="doc-generator",
        )
    except Exception as e:  # noqa: BLE001
        return SubsectionResult(
            title=subsection_title, query=query, body_md="", error=f"{type(e).__name__}: {e}",
            elapsed_s=time.time() - t0,
        )
    body, sources = parse_sources_block(answer if isinstance(answer, str) else str(answer))
    body = strip_leading_heading(body)
    flags = detect_flags(body)
    return SubsectionResult(
        title=subsection_title, query=query, body_md=body,
        sources=sources, flags=flags, elapsed_s=time.time() - t0,
    )


def flatten_required(items: Any) -> list[str]:
    """Some skeletons have plain strings in sections_required, others have nested dicts
    like `{title, sections_required: [...]}`. Flatten everything into one list of titles."""
    out: list[str] = []
    if not items:
        return out
    if isinstance(items, str):
        return [items]
    if isinstance(items, dict):
        title = items.get("title")
        if title:
            out.append(title)
        out.extend(flatten_required(items.get("sections_required")))
        return out
    if isinstance(items, list):
        for it in items:
            out.extend(flatten_required(it))
        return out
    return [str(items)]


async def fill_section(workspace_id: str, section: dict, top_k: int) -> SectionResult:
    sid = str(section.get("id", "?"))
    required = flatten_required(section.get("sections_required")) or [section.get("title", "Content")]
    print(f"\n→ Section {sid}  '{section.get('title')}'  ({len(required)} subsections)")
    res = SectionResult(
        section_id=sid,
        title=section.get("title", ""),
        feature=section.get("feature"),
        audience=list(section.get("__audience", []) or []),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    for sub_title in required:
        print(f"   · {sub_title} ", end="", flush=True)
        sub = await fill_subsection(workspace_id, section, sub_title, top_k)
        flag_str = ", ".join(f.get("kind", "?") for f in sub.flags) or "ok"
        print(f"[{sub.elapsed_s:5.1f}s, sources={len(sub.sources)}, flags={flag_str}]"
              + (f"  ERROR: {sub.error}" if sub.error else ""))
        res.subsections.append(sub)
    return res


# ─────────────────────── rendering ──────────────────────────────────────

def render_section_md(sec: SectionResult, skeleton_section: dict) -> str:
    out: list[str] = [f"# {sec.section_id}  {sec.title}", ""]
    if sec.feature:
        out.append(f"_Feature: `{sec.feature}` · Audience: {', '.join(sec.audience) or '—'}_")
        out.append("")
    intent = skeleton_section.get("intent")
    if intent:
        out.append(f"> {intent}")
        out.append("")
    for sub in sec.subsections:
        out.append(f"## {sub.title}")
        out.append("")
        if sub.error:
            out.append(f"*Generation error: {sub.error}*")
            out.append("")
            continue
        if sub.flags:
            tags = " ".join(f"`⚠ {f['kind']}`" for f in sub.flags)
            out.append(tags)
            out.append("")
        out.append(sub.body_md.strip())
        out.append("")
        if sub.sources:
            out.append("**Sources:**")
            for s in sub.sources:
                out.append(f"- {s['icon']} [{s['title']}]({s['url']})")
            out.append("")
    return "\n".join(out)


def section_to_dict(sec: SectionResult) -> dict[str, Any]:
    return {
        "section_id":    sec.section_id,
        "title":         sec.title,
        "feature":       sec.feature,
        "audience":      sec.audience,
        "generated_at":  sec.generated_at,
        "subsections": [
            {
                "title":     s.title,
                "query":     s.query,
                "body_md":   s.body_md,
                "sources":   s.sources,
                "flags":     s.flags,
                "elapsed_s": round(s.elapsed_s, 2),
                "error":     s.error,
            }
            for s in sec.subsections
        ],
    }


# ─────────────────────── main ───────────────────────────────────────────

async def main_async(args: argparse.Namespace) -> int:
    skel_path = Path(args.skeleton)
    if not skel_path.is_file():
        print(f"skeleton not found: {skel_path}", file=sys.stderr); return 2
    text = skel_path.read_text()
    if skel_path.suffix.lower() == ".json":
        skeleton = json.loads(text)
    else:
        skeleton = yaml.safe_load(text)

    sections = list(iter_leaf_sections(skeleton))
    if args.section:
        sections = [(s, sid) for s, sid in sections if sid == args.section]
        if not sections:
            print(f"section id '{args.section}' not found in skeleton", file=sys.stderr); return 2
    if args.epic:
        # Filter sections whose feature is part of the named epic. Mapping is
        # encoded in the skeleton's `epic_features` block when present, else
        # we accept either an `epic` field on the section or epic == feature.
        epic_map = (skeleton.get("epic_features") or {}).get(args.epic) or []
        before = len(sections)
        sections = [
            (s, sid) for s, sid in sections
            if (s.get("epic") == args.epic) or (s.get("feature") in epic_map)
        ]
        print(f"Filtered by epic={args.epic}: {before} → {len(sections)} sections")
        if not sections:
            print(
                f"epic '{args.epic}' produced 0 sections. Add 'epic_features' map to "
                f"the skeleton or set 'epic' on sections.", file=sys.stderr,
            )
            return 2

    fmt = "json" if skel_path.suffix.lower() == ".json" else "yaml"
    print(f"Skeleton: {skel_path.name}  ({skeleton.get('guide')}, {fmt}, {len(sections)} leaf sections)")

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for section, sid in sections:
        sid_safe = sid.replace(".", "_")
        if out_dir and not args.force:
            md_path = out_dir / f"section-{sid_safe}.md"
            if md_path.exists():
                print(f"\nskip   section {sid} (output exists: {md_path.name}; use --force to regen)")
                continue
        result = await fill_section(args.workspace, section, args.top_k)
        md = render_section_md(result, section)
        if out_dir:
            json_path = out_dir / f"section-{sid_safe}.json"
            md_path   = out_dir / f"section-{sid_safe}.md"
            json_path.write_text(json.dumps(section_to_dict(result), ensure_ascii=False, indent=2))
            md_path.write_text(md)
            print(f"   wrote {md_path} ({len(md)}b)  +  {json_path.name}")
        else:
            print("\n" + "═" * 90)
            print(md)
            print("═" * 90)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--skeleton", required=True)
    p.add_argument("--section", default=None, help="Only generate this section id (e.g. 2.1)")
    p.add_argument("--epic", default=None,
                   help="Only generate sections belonging to this epic (e.g. DPLAT-EPIC-04)")
    p.add_argument("--top-k", type=int, default=25)
    p.add_argument("--out", default=None,
                   help="If set, write section-<id>.{md,json} files instead of stdout")
    p.add_argument("--force", action="store_true",
                   help="Regenerate sections even if output already exists in --out")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
