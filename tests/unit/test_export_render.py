from datetime import UTC, datetime

from metronix.core.models import MemoryKind, MemoryRecord, MemoryScope, RawDocument
from metronix.export.models import ExportScope
from metronix.export.render import build_manifest, render_agent_memory, render_document


def test_render_agent_memory_includes_fields_and_real_id():
    rec = MemoryRecord(
        workspace_id="ws1",
        agent_id="agent/one",
        scope=MemoryScope.PER_AGENT,
        kind=MemoryKind.FACT,
        content="the sky is blue",
        tags=["color"],
    )
    md = render_agent_memory("agent/one", "ws1", [rec])
    assert "agent/one" in md  # real id preserved verbatim
    assert "the sky is blue" in md
    assert "fact" in md and "color" in md


def test_render_document_has_front_matter_and_full_content():
    doc = RawDocument(
        workspace_id="ws1",
        connector_type="jira",
        source_id="PROJ-1",
        title="Bug",
        content="full body text",
        url="http://j/PROJ-1",
        author="alice",
        metadata={"status": "Open"},
    )
    md = render_document(doc)
    assert md.startswith("---")  # YAML front matter
    assert "PROJ-1" in md and "full body text" in md and "alice" in md


def test_manifest_shape():
    man = build_manifest(
        generated_at=datetime(2026, 6, 24, tzinfo=UTC),
        scope=ExportScope(workspace_id="ws1"),
        workspaces=["ws1"],
        agents=[
            {
                "agent_id": "agent/one",
                "file": "ws1/memory/agent-one.md",
                "registered": False,
                "record_count": 1,
            }
        ],
        counts={"workspaces": 1, "agents": 1, "memory_records": 1, "documents": 0},
        limitations=["uploads are text only"],
    )
    assert man["format_version"] == 1
    assert man["counts"]["agents"] == 1
    assert man["agents"][0]["agent_id"] == "agent/one"
