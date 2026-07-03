#!/usr/bin/env python3
"""Migrate a Hermes llm-wiki directory into Metronix's Knowledge Base.

Walks $WIKI_PATH (or --wiki-path), parses each page's YAML frontmatter, and
POSTs it to Metronix's POST /api/v1/knowledge/store endpoint with a
deterministic doc_label so re-running the migration updates existing
documents instead of duplicating them.

Usage:
    python scripts/migrate_wiki.py --wiki-path ~/wiki --base-url http://localhost:8000 \
        --workspace-id MTRNIX --auth-token $METRONIX_AUTH_TOKEN
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import yaml

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugin"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from metronix.client import MetronixClient  # noqa: E402

DEFAULT_SCOPE_DIRS = ("raw", "entities", "concepts", "comparisons", "queries")
SKIP_FILENAMES = {"SCHEMA.md", "index.md"}


def iter_wiki_pages(wiki_path: Path, *, include_archive: bool = False) -> list[Path]:
    """Return every wiki page under the default (or archive) scope.

    Only raw/, entities/, concepts/, comparisons/, and queries/ are ingested
    by default -- SCHEMA.md, index.md, and log*.md are navigation/meta
    files, not knowledge content. _archive/** holds superseded pages and is
    skipped unless include_archive is set, in which case archived pages are
    included alongside the default scope.
    """
    pages: list[Path] = []
    for scope_dir in DEFAULT_SCOPE_DIRS:
        root = wiki_path / scope_dir
        if not root.is_dir():
            continue
        for md_file in sorted(root.rglob("*.md")):
            if md_file.name in SKIP_FILENAMES or md_file.name.startswith("log"):
                continue
            is_archived = "_archive" in md_file.relative_to(wiki_path).parts
            if is_archived and not include_archive:
                continue
            pages.append(md_file)
    return pages


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a wiki page into (frontmatter dict, full original text).

    Returns an empty dict if the file has no ``---``-delimited frontmatter
    block, or if the block isn't valid YAML mapping. The full original text
    (frontmatter included) is always returned as the second element -- it
    becomes the stored document content so tags/type stay visible to
    keyword search, not just structured metadata.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw_frontmatter = text[4:end]
    try:
        frontmatter = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(frontmatter, dict):
        return {}, text
    return frontmatter, text


def build_doc_label(wiki_relpath: str) -> str:
    digest = hashlib.sha256(wiki_relpath.encode("utf-8")).hexdigest()[:16]
    return f"hermes-wiki-{digest}"


def build_metadata(
    frontmatter: dict[str, Any], *, wiki_relpath: str, page_type: str
) -> dict[str, str]:
    metadata: dict[str, str] = {"wiki_relpath": wiki_relpath, "page_type": page_type}
    for key in ("type", "created", "updated", "confidence"):
        value = frontmatter.get(key)
        if value:
            metadata[key] = str(value)
    if frontmatter.get("contested"):
        metadata["contested"] = "true"
    for key in ("tags", "sources", "contradictions"):
        value = frontmatter.get(key)
        if isinstance(value, list) and value:
            metadata[key] = ",".join(str(v) for v in value)
    return metadata


def migrate(
    wiki_path: Path, client: MetronixClient, *, include_archive: bool = False
) -> dict[str, int]:
    counts = {"stored": 0, "failed": 0}
    for page in iter_wiki_pages(wiki_path, include_archive=include_archive):
        wiki_relpath = page.relative_to(wiki_path).as_posix()
        page_type = page.relative_to(wiki_path).parts[0]
        try:
            text = page.read_text(encoding="utf-8")
            frontmatter, content = parse_frontmatter(text)
            title = str(frontmatter.get("title") or page.stem)
            metadata = build_metadata(frontmatter, wiki_relpath=wiki_relpath, page_type=page_type)
            doc_label = build_doc_label(wiki_relpath)
            client.store_document(
                content=content,
                title=title,
                doc_label=doc_label,
                source_type="hermes_llm_wiki",
                metadata=metadata,
            )
            counts["stored"] += 1
            print(f"stored  {wiki_relpath} -> {doc_label}")
        except Exception as exc:  # noqa: BLE001 - per-file isolation, migration continues
            counts["failed"] += 1
            print(f"FAILED  {wiki_relpath}: {exc}", file=sys.stderr)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wiki-path", default=os.environ.get("WIKI_PATH", str(Path.home() / "wiki"))
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--auth-token", default=os.environ.get("METRONIX_AUTH_TOKEN", ""))
    parser.add_argument("--email", default=os.environ.get("METRONIX_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("METRONIX_PASSWORD", ""))
    parser.add_argument("--include-archive", action="store_true")
    args = parser.parse_args()

    wiki_path = Path(args.wiki_path).expanduser()
    if not wiki_path.is_dir():
        print(f"wiki path not found: {wiki_path}", file=sys.stderr)
        return 1

    client = MetronixClient(
        base_url=args.base_url,
        workspace_id=args.workspace_id,
        auth_token=args.auth_token,
        email=args.email,
        password=args.password,
    )

    counts = migrate(wiki_path, client, include_archive=args.include_archive)
    print(f"\n{counts['stored']} stored, {counts['failed']} failed")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
