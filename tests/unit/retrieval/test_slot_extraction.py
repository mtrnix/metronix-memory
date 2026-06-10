"""Slot extraction + channel-trigger union (MTRNIX-397, B0 / M7 / E1)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from metatron.retrieval.search import (
    _build_recall_context,
    _extract_fast_signals,
    _parse_slots,
    extract_slots,
)

# -- _parse_slots (pure) ----------------------------------------------------


def test_parse_slots_valid() -> None:
    raw = json.dumps(
        {
            "date_range": ["2026-06-08", "2026-06-14"],
            "people": ["Alice", "Bob"],
            "jira_keys": ["mtrnix-9"],
            "entities": ["Project X"],
            "is_activity": True,
            "needs_retrieval": True,
        }
    )
    slots = _parse_slots(raw)
    assert slots is not None
    assert slots["date_range"] == ("2026-06-08", "2026-06-14")
    assert slots["people"] == ["Alice", "Bob"]
    assert slots["jira_keys"] == ["MTRNIX-9"]  # upper-cased
    assert slots["entities"] == ["Project X"]
    assert slots["is_activity"] is True
    assert slots["needs_retrieval"] is True


def test_parse_slots_strips_markdown_fences() -> None:
    raw = '```json\n{"date_range": null, "people": [], "jira_keys": [], "entities": [], ' \
        '"is_activity": false, "needs_retrieval": true}\n```'
    slots = _parse_slots(raw)
    assert slots is not None
    assert slots["date_range"] is None
    assert slots["needs_retrieval"] is True


def test_parse_slots_malformed_returns_none() -> None:
    assert _parse_slots("not json at all") is None
    assert _parse_slots("") is None
    assert _parse_slots('{"date_range": [') is None  # truncated


def test_parse_slots_non_dict_returns_none() -> None:
    assert _parse_slots("[1, 2, 3]") is None


def test_parse_slots_defaults_for_missing_keys() -> None:
    slots = _parse_slots("{}")
    assert slots == {
        "date_range": None,
        "people": [],
        "jira_keys": [],
        "entities": [],
        "is_activity": False,
        "needs_retrieval": True,  # default-true: retrieve unless told otherwise
    }


def test_parse_slots_bad_date_range_shape_is_none() -> None:
    slots = _parse_slots('{"date_range": ["2026-06-08"]}')  # only one element
    assert slots is not None
    assert slots["date_range"] is None


# -- extract_slots (LLM wrapper, mocked) ------------------------------------


def test_extract_slots_flag_off_skips_llm() -> None:
    s = SimpleNamespace(retrieval_slot_extraction_enabled=False)
    with patch("metatron.retrieval.search.chat_completion") as mock_llm:
        assert extract_slots("next week tasks", s) is None
        mock_llm.assert_not_called()


def test_extract_slots_flag_on_parses() -> None:
    s = SimpleNamespace(
        retrieval_slot_extraction_enabled=True, retrieval_slot_extraction_timeout=6
    )
    payload = json.dumps(
        {
            "date_range": ["2026-06-08", "2026-06-14"],
            "people": [],
            "jira_keys": [],
            "entities": [],
            "is_activity": True,
            "needs_retrieval": True,
        }
    )
    with patch("metatron.retrieval.search.chat_completion", return_value=payload) as mock_llm:
        slots = extract_slots("next week tasks", s)
        assert slots is not None
        assert slots["is_activity"] is True
        assert mock_llm.call_args.kwargs["call_site"] == "slot_extraction"


def test_extract_slots_llm_exception_returns_none() -> None:
    s = SimpleNamespace(
        retrieval_slot_extraction_enabled=True, retrieval_slot_extraction_timeout=6
    )
    with patch("metatron.retrieval.search.chat_completion", side_effect=Exception("boom")):
        assert extract_slots("next week tasks", s) is None


# -- _extract_fast_signals ISO range (M7) -----------------------------------


def test_extract_fast_signals_iso_range_expands() -> None:
    _, dates = _extract_fast_signals("tasks for the week 2026-06-08..2026-06-10")
    assert dates is not None
    assert "2026-06-08" in dates and "2026-06-09" in dates and "2026-06-10" in dates


def test_extract_fast_signals_single_iso_unchanged() -> None:
    _, dates = _extract_fast_signals("what happened on 2026-06-08")
    assert dates == ("2026-06-08",)


# -- _build_recall_context union (B0 / E1) ----------------------------------


def test_build_recall_context_unions_slots() -> None:
    slots = {
        "date_range": ("2026-06-08", "2026-06-09"),
        "people": ["Alice"],
        "jira_keys": ["MTRNIX-9"],
        "entities": ["Project X"],
        "is_activity": True,
        "needs_retrieval": True,
    }
    ctx = _build_recall_context(
        original_query="what are the plans",  # no regex signals
        translated_query="what are the plans",
        expanded_query="what are the plans",
        detected_language="en",
        workspace_id="MTRNIX",
        slots=slots,
    )
    assert "MTRNIX-9" in ctx.extracted_jira_keys
    assert "Alice" in ctx.detected_person
    assert "Project X" in ctx.extracted_title_entities
    assert ctx.is_activity_query is True
    assert ctx.extracted_dates is not None
    assert "2026-06-08" in ctx.extracted_dates and "2026-06-09" in ctx.extracted_dates


def test_build_recall_context_no_slots_is_regex_only() -> None:
    ctx = _build_recall_context(
        original_query="status of MTRNIX-104",
        translated_query="status of MTRNIX-104",
        expanded_query="status of MTRNIX-104",
        detected_language="en",
        workspace_id="MTRNIX",
        slots=None,
    )
    assert "MTRNIX-104" in ctx.extracted_jira_keys  # regex floor still works
