"""Sanity: new activity/agent event constants exist with stable string values."""

from metronix.core.events import (
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_STATUS_CHANGED,
    AGENT_UPDATED,
    DOCUMENT_ACCESSED,
    ERROR_OCCURRED,
    MEMORY_PROMOTED,
    TOOL_CALLED,
)


def test_activity_event_constants_present() -> None:
    assert MEMORY_PROMOTED == "memory_promoted"
    assert DOCUMENT_ACCESSED == "document_accessed"
    assert TOOL_CALLED == "tool_called"
    assert AGENT_CREATED == "agent_created"
    assert AGENT_UPDATED == "agent_updated"
    assert AGENT_STATUS_CHANGED == "agent_status_changed"
    assert AGENT_DELETED == "agent_deleted"
    assert ERROR_OCCURRED == "error_occurred"
