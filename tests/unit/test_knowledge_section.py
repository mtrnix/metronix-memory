"""Knowledge section formatter (MTRNIX-372 P2)."""

from metatron.memory.knowledge_section import format_knowledge_fragments


def test_format_fragments() -> None:
    frags = [
        {"title": "Doc A", "url": "http://a", "text": "alpha beta " * 40},
        {"title": "Doc B", "content": "gamma", "source_type": "confluence"},
    ]
    out, n = format_knowledge_fragments(frags)
    assert n == 2
    assert "Doc A" in out
    assert "http://a" in out
    assert "gamma" in out
    # excerpt capped at 240 chars per fragment
    assert all(len(line) < 300 for line in out.splitlines())


def test_format_empty() -> None:
    out, n = format_knowledge_fragments([])
    assert out == ""
    assert n == 0
