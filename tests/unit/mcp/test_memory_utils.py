"""Unit tests for MCP memory utility helpers (PROJ-314)."""

from __future__ import annotations

import pytest

from metronix.core.models import LifecycleStatus
from metronix.mcp.tools._memory_utils import parse_status_filter, validate_importance_score


class TestParseStatusFilter:
    def test_none_returns_default_active(self) -> None:
        out = parse_status_filter(None)
        assert out == [LifecycleStatus.ACTIVE]

    def test_all_sentinel_disables_filter(self) -> None:
        assert parse_status_filter(["all"]) is None

    def test_valid_multi_value(self) -> None:
        out = parse_status_filter(["active", "candidate"])
        assert out == [LifecycleStatus.ACTIVE, LifecycleStatus.CANDIDATE]

    def test_invalid_raises_with_hint(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            parse_status_filter(["bogus"])
        # Hint should list valid values incl. 'all'.
        try:
            parse_status_filter(["nope"])
        except ValueError as exc:
            assert "all" in str(exc)
            assert "active" in str(exc)

    def test_empty_list_returns_empty_list(self) -> None:
        """An empty list is not the same as None — it simply parses zero items."""
        out = parse_status_filter([])
        assert out == []


class TestValidateImportanceScore:
    """Regression tests for #455 — the MCP tools stored any float unchecked."""

    @pytest.mark.parametrize("value", [0.0, 0.25, 0.5, 1.0])
    def test_in_range_passes_through_as_float(self, value: float) -> None:
        out = validate_importance_score(value)
        assert out == value
        assert isinstance(out, float)

    def test_integer_bounds_are_coerced(self) -> None:
        assert validate_importance_score(0) == 0.0
        assert validate_importance_score(1) == 1.0

    @pytest.mark.parametrize("value", [-0.01, 1.01, 999.0, -1000.0])
    def test_out_of_range_raises(self, value: float) -> None:
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            validate_importance_score(value)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_raises(self, value: float) -> None:
        """NaN is rejected by the range check itself: NaN comparisons are all False."""
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            validate_importance_score(value)

    @pytest.mark.parametrize("value", ["abc", None, [], {}])
    def test_non_numeric_raises_value_error(self, value: object) -> None:
        """Callers map ValueError to INVALID_PARAMS; bare float() gave INTERNAL_ERROR."""
        with pytest.raises(ValueError, match="must be a number"):
            validate_importance_score(value)  # type: ignore[arg-type]

    def test_numeric_string_is_accepted(self) -> None:
        """float() already accepted these, so rejecting them would be a new break."""
        assert validate_importance_score("0.75") == 0.75  # type: ignore[arg-type]

    def test_message_reports_the_offending_value(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            validate_importance_score(999.0)
        assert "999.0" in str(excinfo.value)
