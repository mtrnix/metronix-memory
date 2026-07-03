from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from migrate_wiki import (  # noqa: E402
    build_doc_label,
    build_metadata,
    iter_wiki_pages,
    migrate,
    parse_frontmatter,
)


def test_parse_frontmatter_extracts_yaml_block():
    text = (
        "---\n"
        "title: GPT-4\n"
        "type: entity\n"
        "tags: [model, openai]\n"
        "---\n"
        "# GPT-4\n\nBody text.\n"
    )

    frontmatter, content = parse_frontmatter(text)

    assert frontmatter["title"] == "GPT-4"
    assert frontmatter["tags"] == ["model", "openai"]
    assert content == text


def test_parse_frontmatter_handles_missing_frontmatter():
    text = "# No frontmatter\n\nJust a page.\n"

    frontmatter, content = parse_frontmatter(text)

    assert frontmatter == {}
    assert content == text


def test_parse_frontmatter_handles_malformed_yaml():
    text = "---\ntitle: [unterminated\n---\nBody\n"

    frontmatter, content = parse_frontmatter(text)

    assert frontmatter == {}
    assert content == text


def test_build_doc_label_is_deterministic_and_path_specific():
    label_a = build_doc_label("entities/gpt-4.md")
    label_b = build_doc_label("entities/gpt-4.md")
    label_c = build_doc_label("entities/claude.md")

    assert label_a == label_b
    assert label_a.startswith("hermes-wiki-")
    assert label_a != label_c


def test_build_metadata_stringifies_and_joins_lists():
    frontmatter = {
        "type": "entity",
        "tags": ["model", "openai"],
        "sources": ["raw/articles/a.md"],
        "confidence": "high",
        "contested": True,
    }

    metadata = build_metadata(frontmatter, wiki_relpath="entities/gpt-4.md", page_type="entities")

    assert metadata["wiki_relpath"] == "entities/gpt-4.md"
    assert metadata["page_type"] == "entities"
    assert metadata["type"] == "entity"
    assert metadata["tags"] == "model,openai"
    assert metadata["sources"] == "raw/articles/a.md"
    assert metadata["confidence"] == "high"
    assert metadata["contested"] == "true"


def test_iter_wiki_pages_applies_default_scope(tmp_path: Path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "gpt-4.md").write_text("x")
    (tmp_path / "concepts").mkdir()
    (tmp_path / "concepts" / "alignment.md").write_text("x")
    (tmp_path / "index.md").write_text("x")
    (tmp_path / "SCHEMA.md").write_text("x")
    (tmp_path / "log.md").write_text("x")
    (tmp_path / "entities" / "_archive").mkdir()
    (tmp_path / "entities" / "_archive" / "old.md").write_text("x")

    pages = {p.relative_to(tmp_path).as_posix() for p in iter_wiki_pages(tmp_path)}

    assert pages == {"entities/gpt-4.md", "concepts/alignment.md"}


def test_iter_wiki_pages_includes_archive_when_requested(tmp_path: Path):
    (tmp_path / "entities" / "_archive").mkdir(parents=True)
    (tmp_path / "entities" / "_archive" / "old.md").write_text("x")

    pages = {p.relative_to(tmp_path).as_posix() for p in iter_wiki_pages(tmp_path, include_archive=True)}

    assert pages == {"entities/_archive/old.md"}


def test_migrate_stores_each_page_and_continues_past_failures(tmp_path: Path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "good.md").write_text("---\ntitle: Good\n---\nbody")
    (tmp_path / "entities" / "bad.md").write_text("body without frontmatter")

    client = MagicMock()
    client.store_document.side_effect = [None, RuntimeError("network error")]

    counts = migrate(tmp_path, client)

    assert client.store_document.call_count == 2
    assert counts == {"stored": 1, "failed": 1}
