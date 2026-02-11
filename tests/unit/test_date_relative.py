"""Tests for relative date extraction in ingestion/processors/dates.py."""

from __future__ import annotations

from datetime import datetime, timedelta

from metatron.ingestion.processors.dates import (
    extract_date_range,
    get_dates_in_range,
    _this_week,
    _last_week,
    _this_month,
    _last_month,
)


class TestThisWeek:
    def test_this_week_en(self) -> None:
        result = extract_date_range("what happened this week?")
        assert result is not None
        start, end = result
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        assert start <= today_str <= end

    def test_current_week_en(self) -> None:
        result = extract_date_range("current week updates")
        assert result is not None

    def test_this_week_ru(self) -> None:
        result = extract_date_range("что было на этой неделе?")
        assert result is not None
        start, end = result
        now = datetime.now()
        assert start <= now.strftime("%Y-%m-%d") <= end

    def test_this_week_ru_variant(self) -> None:
        result = extract_date_range("текущая неделя")
        assert result is not None

    def test_this_week_ru_variant2(self) -> None:
        result = extract_date_range("эта неделя")
        assert result is not None

    def test_this_week_monday_to_sunday(self) -> None:
        start, end = _this_week()
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert start_dt.weekday() == 0  # Monday
        assert end_dt.weekday() == 6  # Sunday
        assert (end_dt - start_dt).days == 6


class TestLastWeek:
    def test_last_week_en(self) -> None:
        result = extract_date_range("what happened last week?")
        assert result is not None
        start, end = result
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        # Last week should be entirely before this week's Monday
        assert end < today_str or end <= today_str

    def test_last_week_ru(self) -> None:
        result = extract_date_range("на прошлой неделе")
        assert result is not None

    def test_last_week_ru_variant(self) -> None:
        result = extract_date_range("прошлая неделя")
        assert result is not None

    def test_last_week_monday_to_sunday(self) -> None:
        start, end = _last_week()
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert start_dt.weekday() == 0  # Monday
        assert end_dt.weekday() == 6  # Sunday
        assert (end_dt - start_dt).days == 6

    def test_last_week_before_this_week(self) -> None:
        last_start, last_end = _last_week()
        this_start, _ = _this_week()
        assert last_end < this_start


class TestThisMonth:
    def test_this_month_en(self) -> None:
        result = extract_date_range("what happened this month?")
        assert result is not None
        start, end = result
        now = datetime.now()
        assert start == now.replace(day=1).strftime("%Y-%m-%d")

    def test_current_month_en(self) -> None:
        result = extract_date_range("current month report")
        assert result is not None

    def test_this_month_ru(self) -> None:
        result = extract_date_range("в этом месяце")
        assert result is not None

    def test_this_month_ru_variant(self) -> None:
        result = extract_date_range("текущий месяц")
        assert result is not None

    def test_this_month_first_to_last(self) -> None:
        start, end = _this_month()
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert start_dt.day == 1
        # End should be last day of current month
        assert start_dt.month == end_dt.month


class TestLastMonth:
    def test_last_month_en(self) -> None:
        result = extract_date_range("last month")
        assert result is not None

    def test_last_month_ru(self) -> None:
        result = extract_date_range("в прошлом месяце")
        assert result is not None

    def test_last_month_first_to_last(self) -> None:
        start, end = _last_month()
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        assert start_dt.day == 1
        assert start_dt.month == end_dt.month

    def test_last_month_before_this_month(self) -> None:
        _, last_end = _last_month()
        this_start, _ = _this_month()
        assert last_end < this_start


class TestToday:
    def test_today_en(self) -> None:
        result = extract_date_range("what happened today?")
        assert result is not None
        start, end = result
        today = datetime.now().strftime("%Y-%m-%d")
        assert start == end == today

    def test_today_ru(self) -> None:
        result = extract_date_range("что было сегодня?")
        assert result is not None
        start, end = result
        assert start == end == datetime.now().strftime("%Y-%m-%d")


class TestYesterday:
    def test_yesterday_en(self) -> None:
        result = extract_date_range("what happened yesterday?")
        assert result is not None
        start, end = result
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert start == end == yesterday

    def test_yesterday_ru(self) -> None:
        result = extract_date_range("вчера")
        assert result is not None


class TestNoDateMatch:
    def test_plain_query(self) -> None:
        result = extract_date_range("what is Metatron?")
        assert result is None

    def test_empty_string(self) -> None:
        result = extract_date_range("")
        assert result is None


class TestGetDatesInRange:
    def test_single_day(self) -> None:
        dates = get_dates_in_range("2026-02-11", "2026-02-11")
        assert dates == ["2026-02-11"]

    def test_week(self) -> None:
        dates = get_dates_in_range("2026-02-09", "2026-02-15")
        assert len(dates) == 7
        assert dates[0] == "2026-02-09"
        assert dates[-1] == "2026-02-15"
