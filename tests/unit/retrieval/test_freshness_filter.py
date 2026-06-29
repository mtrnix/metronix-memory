"""Freshness filter pushdown (MTRNIX-313).

Tests the flag-off byte-identical invariant (``_build_freshness_filter``
returns ``None``) plus the combine-filters helper so access + freshness
pushdown land in one Qdrant Filter.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def test_build_freshness_filter_none_when_flag_off() -> None:
    from metronix.retrieval.search import _build_freshness_filter

    settings = MagicMock(freshness_kb_search_filter_enabled=False)
    assert _build_freshness_filter(settings) is None


def test_build_freshness_filter_none_when_settings_is_none() -> None:
    from metronix.retrieval.search import _build_freshness_filter

    assert _build_freshness_filter(None) is None


def test_build_freshness_filter_excludes_archived_and_superseded_when_on() -> None:
    from metronix.retrieval.search import _build_freshness_filter

    settings = MagicMock(freshness_kb_search_filter_enabled=True)
    flt = _build_freshness_filter(settings)
    assert flt is not None
    # must_not conditions cover both terminal states.
    excluded = set()
    for cond in flt.must_not or []:
        key = getattr(cond, "key", None)
        match = getattr(cond, "match", None)
        val = getattr(match, "value", None) if match is not None else None
        if key == "status" and val is not None:
            excluded.add(val)
    assert excluded == {"archived", "superseded"}


def test_combine_filters_returns_none_when_both_none() -> None:
    from metronix.retrieval.channels import _combine_filters

    assert _combine_filters(None, None) is None


def test_combine_filters_returns_freshness_when_access_none() -> None:
    from metronix.retrieval.channels import _combine_filters
    from metronix.retrieval.search import _build_freshness_filter

    settings = MagicMock(freshness_kb_search_filter_enabled=True)
    fresh = _build_freshness_filter(settings)
    assert _combine_filters(None, fresh) is fresh


def test_combine_filters_returns_access_when_freshness_none() -> None:
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    from metronix.retrieval.channels import _combine_filters

    access = Filter(should=[FieldCondition(key="access_groups", match=MatchValue(value="x"))])
    assert _combine_filters(access, None) is access


def test_combine_filters_merges_must_not_lists() -> None:
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    from metronix.retrieval.channels import _combine_filters
    from metronix.retrieval.search import _build_freshness_filter

    access = Filter(must=[FieldCondition(key="workspace_id", match=MatchValue(value="ws1"))])
    fresh = _build_freshness_filter(MagicMock(freshness_kb_search_filter_enabled=True))
    combined = _combine_filters(access, fresh)
    assert combined is not None
    # must preserved from access.
    must_keys = {c.key for c in (combined.must or [])}
    assert "workspace_id" in must_keys
    # must_not picked up from freshness.
    must_not_values = set()
    for c in combined.must_not or []:
        val = getattr(c.match, "value", None)
        if val is not None:
            must_not_values.add(val)
    assert must_not_values == {"archived", "superseded"}
