"""Anti-hallucination ticket guard (MTRNIX-397, H1)."""

from __future__ import annotations

from metatron.retrieval.search import find_ungrounded_tickets


def test_no_tickets_in_answer() -> None:
    assert find_ungrounded_tickets("A plain answer with no tickets.", []) == []


def test_grounded_ticket_in_title_is_ok() -> None:
    results = [{"title": "[MTRNIX-281] Analyze papers", "text": "..."}]
    assert find_ungrounded_tickets("See MTRNIX-281 for details.", results) == []


def test_grounded_ticket_in_text_is_ok() -> None:
    results = [{"title": "Daily", "text": "work on MTRNIX-9 continues"}]
    assert find_ungrounded_tickets("MTRNIX-9 is in progress.", results) == []


def test_grounded_ticket_in_doc_label_is_ok() -> None:
    results = [{"doc_label": "jira:MTRNIX-55", "payload": {}}]
    assert find_ungrounded_tickets("per MTRNIX-55", results) == []


def test_ungrounded_ticket_flagged() -> None:
    results = [{"title": "[MTRNIX-281] Analyze papers", "text": "nothing else"}]
    # MTRNIX-370 is not present anywhere in the sources → hallucinated.
    assert find_ungrounded_tickets("The plan covers MTRNIX-370 and MTRNIX-281.", results) == [
        "MTRNIX-370"
    ]


def test_case_insensitive_grounding() -> None:
    results = [{"text": "mtrnix-42 done"}]
    assert find_ungrounded_tickets("MTRNIX-42 is done", results) == []


def test_multiple_ungrounded_sorted_unique() -> None:
    results = [{"title": "unrelated", "text": "no keys here"}]
    out = find_ungrounded_tickets("MTRNIX-9, MTRNIX-9, ABC-1 and MTRNIX-2", results)
    assert out == ["ABC-1", "MTRNIX-2", "MTRNIX-9"]


def test_grounded_via_payload_data() -> None:
    results = [{"payload": {"data": "discussion about MTRNIX-100"}}]
    assert find_ungrounded_tickets("MTRNIX-100 update", results) == []


def test_substring_ticket_not_treated_as_grounded() -> None:
    """A cited MTRNIX-2 must NOT count as grounded just because sources contain MTRNIX-281
    (exact ticket-key set membership, not substring) — otherwise the metric lies."""
    results = [{"title": "[MTRNIX-281] Analyze papers", "text": "MTRNIX-281 details"}]
    assert find_ungrounded_tickets("Work on MTRNIX-2 continues.", results) == ["MTRNIX-2"]
