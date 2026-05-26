"""Unit tests for asoc_processing — entity mapping, severity, URL hints, deterministic IDs."""

from __future__ import annotations

import pytest

from metatron.connectors.asoc_processing import (
    deterministic_document_id,
    entity_to_markdown,
    entity_to_metadata,
    process_asoc_entity,
    severity_to_label,
)

# ---------------------------------------------------------------------------
# severity_to_label
# ---------------------------------------------------------------------------


class TestSeverityToLabel:
    def test_informational(self) -> None:
        assert severity_to_label(-1) == "informational"

    def test_low(self) -> None:
        assert severity_to_label(1) == "low"

    def test_medium(self) -> None:
        assert severity_to_label(2) == "medium"

    def test_high(self) -> None:
        assert severity_to_label(3) == "high"

    def test_critical(self) -> None:
        assert severity_to_label(4) == "critical"

    def test_none_returns_unknown(self) -> None:
        assert severity_to_label(None) == "unknown"

    def test_unmapped_value_returns_unknown(self) -> None:
        assert severity_to_label(99) == "unknown"


# ---------------------------------------------------------------------------
# deterministic_document_id
# ---------------------------------------------------------------------------


class TestDeterministicDocumentId:
    def test_stability(self) -> None:
        """Same inputs always produce the same ID."""
        doc_id = deterministic_document_id("issue", "abc-123", "some content")
        assert doc_id == deterministic_document_id("issue", "abc-123", "some content")

    def test_content_sensitive(self) -> None:
        """Different content produces a different ID."""
        a = deterministic_document_id("issue", "abc-123", "content A")
        b = deterministic_document_id("issue", "abc-123", "content B")
        assert a != b

    def test_entity_id_sensitive(self) -> None:
        """Different entity_id produces a different ID."""
        a = deterministic_document_id("issue", "id-1", "same content")
        b = deterministic_document_id("issue", "id-2", "same content")
        assert a != b

    def test_entity_type_sensitive(self) -> None:
        """Different entity_type produces a different ID."""
        a = deterministic_document_id("issue", "same-id", "same content")
        b = deterministic_document_id("project", "same-id", "same content")
        assert a != b

    def test_length_is_32(self) -> None:
        doc_id = deterministic_document_id("event", "evt-1", "payload")
        assert len(doc_id) == 32

    def test_is_hex_string(self) -> None:
        doc_id = deterministic_document_id("layer", "lyr-1", "hello")
        assert all(c in "0123456789abcdef" for c in doc_id)


# ---------------------------------------------------------------------------
# Fixtures for raw payloads (one per entity type)
# ---------------------------------------------------------------------------

_PROJECT_RAW = {
    "id": "proj-1",
    "name": "My Project",
    "description": "A test project",
    "created_at": "2025-01-01T10:00:00Z",
    "updated_at": "2025-06-01T12:00:00Z",
}

_LAYER_RAW = {
    "id": "layer-1",
    "name": "Frontend",
    "description": "UI layer",
    "kind": "service",
    "created_at": "2025-01-02T10:00:00Z",
    "updated_at": "2025-06-02T12:00:00Z",
}

_ISSUE_RAW = {
    "id": "issue-42",
    "title": "SQL injection",
    "description": "Details about the vuln",
    "severity": 4,
    "status": "open",
    "layer_id": "layer-1",
    "view_id": "ISS-042",
    "created_by": "alice",
    "created_at": "2025-03-01T00:00:00Z",
    "updated_at": "2025-06-10T00:00:00Z",
}

_COMMENT_RAW = {
    "id": "comment-1",
    "body": "This is a comment",
    "author": "bob",
    "issue_id": "issue-42",
    "issue_view_id": "ISS-042",
    "created_at": "2025-04-01T00:00:00Z",
    "updated_at": "2025-04-02T00:00:00Z",
}

_HISTORY_RAW = {
    "id": "history-1",
    "field": "status",
    "old_value": "open",
    "new_value": "resolved",
    "changed_by": "carol",
    "issue_id": "issue-42",
    "issue_view_id": "ISS-042",
    "created_at": "2025-05-01T00:00:00Z",
}

_SCAN_RESULT_RAW = {
    "id": "scan-1",
    "name": "Weekly SAST",
    "scan_type": "sast",
    "status": "completed",
    "issue_count": 7,
    "layer_id": "layer-1",
    "created_at": "2025-05-10T00:00:00Z",
}

_SBOM_RAW = {
    "id": "sbom-1",
    "name": "app-sbom",
    "format": "cyclonedx",
    "version": "1.4",
    "layer_id": "layer-1",
    "created_at": "2025-05-11T00:00:00Z",
}

_DEPENDENCY_RAW = {
    "id": "dep-1",
    "name": "log4j",
    "version": "2.14.1",
    "license": "Apache-2.0",
    "risk_level": 3,
    "layer_id": "layer-1",
    "created_at": "2025-05-12T00:00:00Z",
}

_QUALITY_GATE_RAW = {
    "id": "qg-1",
    "name": "Default Gate",
    "status": "passed",
    "conditions": [{"metric": "coverage", "threshold": 80}],
    "project_id": "proj-1",
    "created_at": "2025-05-13T00:00:00Z",
}

_EVENT_RAW = {
    "id": "evt-1",
    "event_type": "scan_completed",
    "actor": "system",
    "payload": {"scan_id": "scan-1"},
    "project_id": "proj-1",
    "created_at": "2025-05-14T00:00:00Z",
}

_ALL_RAWS: dict[str, dict] = {
    "project": _PROJECT_RAW,
    "layer": _LAYER_RAW,
    "issue": _ISSUE_RAW,
    "comment": _COMMENT_RAW,
    "issue_history": _HISTORY_RAW,
    "scan_result": _SCAN_RESULT_RAW,
    "sbom": _SBOM_RAW,
    "dependency": _DEPENDENCY_RAW,
    "gate": _QUALITY_GATE_RAW,  # canonical entity_type per ASOC analytics docs
    "quality_gate": _QUALITY_GATE_RAW,  # backward-compat alias
    "event": _EVENT_RAW,
}

_PROJECT_ID = "proj-1"


# ---------------------------------------------------------------------------
# process_asoc_entity — one test per type
# ---------------------------------------------------------------------------


class TestProcessAsocEntity:
    def test_project(self) -> None:
        s = process_asoc_entity("project", _PROJECT_RAW)
        assert s["entity_id"] == "proj-1"
        assert s["title"] == "My Project"
        assert s["description"] == "A test project"
        assert s["created_at"] is not None

    def test_layer(self) -> None:
        s = process_asoc_entity("layer", _LAYER_RAW)
        assert s["entity_id"] == "layer-1"
        assert s["title"] == "Frontend"
        assert s["kind"] == "service"

    def test_issue(self) -> None:
        s = process_asoc_entity("issue", _ISSUE_RAW)
        assert s["entity_id"] == "issue-42"
        assert s["severity"] == 4
        assert s["severity_label"] == "critical"
        assert s["view_id"] == "ISS-042"
        assert s["layer_id"] == "layer-1"

    def test_comment(self) -> None:
        s = process_asoc_entity("comment", _COMMENT_RAW)
        assert s["entity_id"] == "comment-1"
        assert s["body"] == "This is a comment"
        assert s["author"] == "bob"
        assert s["issue_id"] == "issue-42"

    def test_issue_history(self) -> None:
        s = process_asoc_entity("issue_history", _HISTORY_RAW)
        assert s["entity_id"] == "history-1"
        assert s["field"] == "status"
        assert s["old_value"] == "open"
        assert s["new_value"] == "resolved"
        assert s["author"] == "carol"

    def test_scan_result(self) -> None:
        s = process_asoc_entity("scan_result", _SCAN_RESULT_RAW)
        assert s["entity_id"] == "scan-1"
        assert s["scan_type"] == "sast"
        assert s["issue_count"] == 7

    def test_sbom(self) -> None:
        s = process_asoc_entity("sbom", _SBOM_RAW)
        assert s["entity_id"] == "sbom-1"
        assert s["format"] == "cyclonedx"
        assert s["version"] == "1.4"

    def test_dependency(self) -> None:
        s = process_asoc_entity("dependency", _DEPENDENCY_RAW)
        assert s["entity_id"] == "dep-1"
        assert s["version"] == "2.14.1"
        assert s["risk_level"] == 3

    def test_quality_gate(self) -> None:
        s = process_asoc_entity("quality_gate", _QUALITY_GATE_RAW)
        assert s["entity_id"] == "qg-1"
        assert s["status"] == "passed"

    def test_event(self) -> None:
        s = process_asoc_entity("event", _EVENT_RAW)
        assert s["entity_id"] == "evt-1"
        assert s["event_type"] == "scan_completed"
        assert s["actor"] == "system"

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown entity_type"):
            process_asoc_entity("unknown_type", {})

    def test_missing_id_raises(self) -> None:
        with pytest.raises(KeyError):
            process_asoc_entity("project", {"name": "no id here"})


# ---------------------------------------------------------------------------
# entity_to_markdown — key substring tests per type
# ---------------------------------------------------------------------------


class TestEntityToMarkdown:
    def _structured(self, entity_type: str) -> dict:
        return process_asoc_entity(entity_type, _ALL_RAWS[entity_type])

    def test_project_contains_title(self) -> None:
        md = entity_to_markdown("project", self._structured("project"))
        assert "My Project" in md

    def test_layer_contains_kind(self) -> None:
        md = entity_to_markdown("layer", self._structured("layer"))
        assert "service" in md

    def test_issue_contains_severity(self) -> None:
        md = entity_to_markdown("issue", self._structured("issue"))
        assert "critical" in md
        assert "ISS-042" in md

    def test_comment_contains_author(self) -> None:
        md = entity_to_markdown("comment", self._structured("comment"))
        assert "bob" in md
        assert "This is a comment" in md

    def test_issue_history_contains_field_change(self) -> None:
        md = entity_to_markdown("issue_history", self._structured("issue_history"))
        assert "status" in md
        assert "resolved" in md

    def test_scan_result_contains_type(self) -> None:
        md = entity_to_markdown("scan_result", self._structured("scan_result"))
        assert "sast" in md

    def test_sbom_contains_format(self) -> None:
        md = entity_to_markdown("sbom", self._structured("sbom"))
        assert "cyclonedx" in md

    def test_dependency_contains_name(self) -> None:
        md = entity_to_markdown("dependency", self._structured("dependency"))
        assert "log4j" in md

    def test_quality_gate_contains_status(self) -> None:
        md = entity_to_markdown("quality_gate", self._structured("quality_gate"))
        assert "passed" in md

    def test_event_contains_event_type(self) -> None:
        md = entity_to_markdown("event", self._structured("event"))
        assert "scan_completed" in md


# ---------------------------------------------------------------------------
# entity_to_metadata — field presence tests per type
# ---------------------------------------------------------------------------


class TestEntityToMetadata:
    def _meta(self, entity_type: str) -> dict:
        s = process_asoc_entity(entity_type, _ALL_RAWS[entity_type])
        return entity_to_metadata(entity_type, s, _PROJECT_ID)

    def test_all_types_have_base_keys(self) -> None:
        for entity_type in _ALL_RAWS:
            m = self._meta(entity_type)
            assert "entity_type" in m
            assert "entity_id" in m
            assert "project_id" in m
            assert m["project_id"] == _PROJECT_ID

    def test_project_extra_keys(self) -> None:
        m = self._meta("project")
        assert m["entity_type"] == "project"

    def test_layer_has_kind(self) -> None:
        m = self._meta("layer")
        assert m["kind"] == "service"

    def test_issue_has_severity(self) -> None:
        m = self._meta("issue")
        assert m["severity_label"] == "critical"
        assert "status" in m
        assert m["view_id"] == "ISS-042"

    def test_comment_has_issue_id(self) -> None:
        m = self._meta("comment")
        assert m["issue_id"] == "issue-42"

    def test_issue_history_has_field(self) -> None:
        m = self._meta("issue_history")
        assert m["field"] == "status"

    def test_scan_result_has_scan_type(self) -> None:
        m = self._meta("scan_result")
        assert m["scan_type"] == "sast"

    def test_sbom_has_format(self) -> None:
        m = self._meta("sbom")
        assert m["format"] == "cyclonedx"

    def test_dependency_has_version(self) -> None:
        m = self._meta("dependency")
        assert m["version"] == "2.14.1"

    def test_quality_gate_has_status(self) -> None:
        m = self._meta("quality_gate")
        assert m["status"] == "passed"

    def test_event_has_event_type(self) -> None:
        m = self._meta("event")
        assert m["event_type"] == "scan_completed"


# ---------------------------------------------------------------------------
# Parent entity fields (T5 additive extension — MTRNIX-355)
# ---------------------------------------------------------------------------


class TestParentEntityFields:
    """Verify parent_entity_type + parent_entity_id added to metadata for child types."""

    def _meta(self, entity_type: str, raw: dict | None = None) -> dict:
        if raw is None:
            raw = _ALL_RAWS[entity_type]
        s = process_asoc_entity(entity_type, raw)
        return entity_to_metadata(entity_type, s, _PROJECT_ID)

    # --- comment ---

    def test_comment_metadata_has_parent_entity_fields(self) -> None:
        m = self._meta("comment")
        assert m["parent_entity_type"] == "issue"
        assert m["parent_entity_id"] == "issue-42"

    def test_comment_metadata_preserves_legacy_keys(self) -> None:
        m = self._meta("comment")
        assert m["issue_id"] == "issue-42"
        assert m["issue_view_id"] == "ISS-042"
        assert m["author"] == "bob"

    # --- issue_history ---

    def test_issue_history_metadata_has_parent_entity_fields(self) -> None:
        m = self._meta("issue_history")
        assert m["parent_entity_type"] == "issue"
        assert m["parent_entity_id"] == "issue-42"

    def test_issue_history_metadata_preserves_legacy_keys(self) -> None:
        m = self._meta("issue_history")
        assert m["issue_id"] == "issue-42"
        assert m["issue_view_id"] == "ISS-042"
        assert m["field"] == "status"

    # --- sbom ---

    def test_sbom_metadata_has_parent_entity_fields(self) -> None:
        m = self._meta("sbom")
        assert m["parent_entity_type"] == "layer"
        assert m["parent_entity_id"] == "layer-1"

    def test_sbom_metadata_preserves_legacy_keys(self) -> None:
        m = self._meta("sbom")
        assert m["layer_id"] == "layer-1"
        assert m["format"] == "cyclonedx"
        assert m["version"] == "1.4"

    # --- dependency ---

    def test_dependency_metadata_has_parent_entity_fields(self) -> None:
        m = self._meta("dependency")
        assert m["parent_entity_type"] == "layer"
        assert m["parent_entity_id"] == "layer-1"

    def test_dependency_metadata_preserves_legacy_keys(self) -> None:
        m = self._meta("dependency")
        assert m["layer_id"] == "layer-1"
        assert m["version"] == "2.14.1"
        assert m["license"] == "Apache-2.0"
        assert m["risk_level"] == "3"

    # --- quality_gate ---

    def test_quality_gate_metadata_has_parent_entity_fields(self) -> None:
        m = self._meta("quality_gate")
        assert m["parent_entity_type"] == "project"
        assert m["parent_entity_id"] == "proj-1"

    def test_quality_gate_metadata_preserves_legacy_keys(self) -> None:
        m = self._meta("quality_gate")
        assert m["status"] == "passed"

    def test_quality_gate_missing_project_id_gives_empty_parent(self) -> None:
        raw_no_proj = {k: v for k, v in _QUALITY_GATE_RAW.items() if k != "project_id"}
        m = self._meta("quality_gate", raw_no_proj)
        assert m["parent_entity_id"] == ""

    # --- event ---

    def test_event_metadata_has_parent_entity_fields(self) -> None:
        m = self._meta("event")
        assert m["parent_entity_type"] == "project"
        assert m["parent_entity_id"] == "proj-1"

    def test_event_metadata_preserves_legacy_keys(self) -> None:
        m = self._meta("event")
        assert m["event_type"] == "scan_completed"
        assert m["actor"] == "system"

    def test_event_missing_project_id_gives_empty_parent(self) -> None:
        raw_no_proj = {k: v for k, v in _EVENT_RAW.items() if k != "project_id"}
        m = self._meta("event", raw_no_proj)
        assert m["parent_entity_id"] == ""

    # --- root types (no parent_entity_* expected) ---

    def test_issue_no_parent_entity_fields(self) -> None:
        m = self._meta("issue")
        assert "parent_entity_type" not in m
        assert "parent_entity_id" not in m

    def test_project_no_parent_entity_fields(self) -> None:
        m = self._meta("project")
        assert "parent_entity_type" not in m
        assert "parent_entity_id" not in m

    def test_layer_no_parent_entity_fields(self) -> None:
        m = self._meta("layer")
        assert "parent_entity_type" not in m
        assert "parent_entity_id" not in m

    def test_scan_result_no_parent_entity_fields(self) -> None:
        m = self._meta("scan_result")
        assert "parent_entity_type" not in m
        assert "parent_entity_id" not in m


# ---------------------------------------------------------------------------
# Canonicalize gate vs quality_gate (MTRNIX-370 Item B)
# ---------------------------------------------------------------------------


class TestGateCanonicalAlias:
    """gate is the canonical entity_type; quality_gate is a backward-compat alias.

    Both must:
    - parse successfully via process_asoc_entity
    - map to resource_type 'project' in metadata (via entity_to_metadata)
    - produce equivalent Documents (same structured dict)
    - produce identical markdown and URL hints
    """

    def test_gate_process_asoc_entity_succeeds(self) -> None:
        s = process_asoc_entity("gate", _QUALITY_GATE_RAW)
        assert s["entity_id"] == "qg-1"
        assert s["status"] == "passed"

    def test_quality_gate_process_asoc_entity_still_works(self) -> None:
        """Backward-compat: quality_gate is still accepted."""
        s = process_asoc_entity("quality_gate", _QUALITY_GATE_RAW)
        assert s["entity_id"] == "qg-1"
        assert s["status"] == "passed"

    def test_gate_and_quality_gate_produce_equivalent_structured_dicts(self) -> None:
        gate = process_asoc_entity("gate", _QUALITY_GATE_RAW)
        qgate = process_asoc_entity("quality_gate", _QUALITY_GATE_RAW)
        assert gate == qgate

    def test_gate_metadata_has_project_resource_type(self) -> None:
        s = process_asoc_entity("gate", _QUALITY_GATE_RAW)
        m = entity_to_metadata("gate", s, _PROJECT_ID)
        assert m["entity_type"] == "gate"
        assert m["parent_entity_type"] == "project"
        assert m["parent_entity_id"] == "proj-1"

    def test_quality_gate_metadata_has_project_resource_type(self) -> None:
        s = process_asoc_entity("quality_gate", _QUALITY_GATE_RAW)
        m = entity_to_metadata("quality_gate", s, _PROJECT_ID)
        assert m["entity_type"] == "quality_gate"
        assert m["parent_entity_type"] == "project"
        assert m["parent_entity_id"] == "proj-1"

    def test_gate_markdown_contains_status(self) -> None:
        s = process_asoc_entity("gate", _QUALITY_GATE_RAW)
        md = entity_to_markdown("gate", s)
        assert "passed" in md
