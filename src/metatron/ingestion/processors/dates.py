"""Date extraction and parsing utilities (RU + EN).

Supports ISO, relative expressions, and named weekdays.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import structlog

logger = structlog.get_logger()

# -- Month / weekday lookup tables ------------------------------------------

MONTHS_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}
MONTHS_RU_TO_NUM = {v: k for k, v in MONTHS_RU.items()}

MONTHS_EN = {
    1: "january",
    2: "february",
    3: "march",
    4: "april",
    5: "may",
    6: "june",
    7: "july",
    8: "august",
    9: "september",
    10: "october",
    11: "november",
    12: "december",
}
MONTHS_EN_TO_NUM = {v: k for k, v in MONTHS_EN.items()}

DAYS_RU = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "среду": 2,
    "четверг": 3,
    "пятница": 4,
    "пятницу": 4,
    "суббота": 5,
    "субботу": 5,
    "воскресенье": 6,
}

DAYS_EN = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# -- Relative date helpers ---------------------------------------------------


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _this_week() -> tuple[str, str]:
    """Monday through Sunday of the current week."""
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    return (_fmt(monday), _fmt(sunday))


def _last_week() -> tuple[str, str]:
    """Monday through Sunday of the previous week."""
    now = datetime.now()
    last_monday = now - timedelta(days=now.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return (_fmt(last_monday), _fmt(last_sunday))


def _this_month() -> tuple[str, str]:
    """First through last day of the current month."""
    now = datetime.now()
    first = now.replace(day=1)
    next_month = first + timedelta(days=32)
    last = next_month.replace(day=1) - timedelta(days=1)
    return (_fmt(first), _fmt(last))


def _last_month() -> tuple[str, str]:
    """First through last day of the previous month."""
    now = datetime.now()
    first_this = now.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return (_fmt(first_prev), _fmt(last_prev))


# -- Single-date extraction -------------------------------------------------


def extract_date_from_text(
    text: str, fallback_year: int | None = None
) -> str | None:  # TODO: async migration
    """Extract a single ISO date (YYYY-MM-DD) from *text*.

    Supports ISO (``2025-12-25``), European (``25.12.2025``),
    Russian (``25 декабря 2025``), and English (``December 25, 2025`` /
    ``25 December 2025``) formats.

    Args:
        text: Input text to search for dates.
        fallback_year: Year to use when date has no explicit year.
            Defaults to the current year.

    Returns:
        ISO date string or ``None``.
    """
    yr = str(fallback_year or datetime.now().year)

    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso_match:
        return iso_match.group(1)

    # European: DD.MM.YYYY
    eu_match = re.search(r"(\d{1,2})\.(\d{2})\.(\d{4})", text)
    if eu_match:
        day, month, year = int(eu_match.group(1)), int(eu_match.group(2)), eu_match.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"

    ru_date = re.search(
        r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if ru_date:
        day = int(ru_date.group(1))
        month = MONTHS_RU_TO_NUM.get(ru_date.group(2).lower(), 0)
        year = ru_date.group(3) or yr
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    en_date1 = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:[,\s]+(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if en_date1:
        month = MONTHS_EN_TO_NUM.get(en_date1.group(1).lower(), 0)
        day = int(en_date1.group(2))
        year = en_date1.group(3) or yr
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    en_date2 = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if en_date2:
        day = int(en_date2.group(1))
        month = MONTHS_EN_TO_NUM.get(en_date2.group(2).lower(), 0)
        year = en_date2.group(3) or yr
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    return None


# -- Date-range extraction ---------------------------------------------------


def extract_date_range(text: str) -> tuple[str, str] | None:  # TODO: async migration
    """Extract a date range from *text*.

    Supports relative expressions in Russian and English (``this week``,
    ``last week``, ``yesterday``, ``последние 7 дней``, ``на этой неделе``,
    etc.) and explicit ranges like ``с 20 по 26 декабря``.

    Returns:
        ``(start_date, end_date)`` in ISO format, or ``None``.
    """
    tl = text.lower()
    today = datetime.now()

    # -- "This week/month" (EN) — check BEFORE "last" patterns --
    if re.search(r"this\s+week|current\s+week", tl):
        return _this_week()
    if re.search(r"this\s+month|current\s+month", tl):
        return _this_month()

    # -- "This week/month" (RU) --
    if re.search(r"эт\w*\s+недел|текущ\w*\s+недел|на\s+этой\s+неделе", tl):
        return _this_week()
    if re.search(r"эт\w*\s+месяц|текущ\w*\s+месяц|в\s+этом\s+месяце", tl):
        return _this_month()

    # -- Russian relative dates --
    if re.search(r"прошл\w*\s+год|в\s+прошлом\s+году|последн\w*\s+год", tl):
        y = today.year - 1
        return (_fmt(datetime(y, 1, 1)), _fmt(datetime(y, 12, 31)))

    if re.search(r"прошл\w*\s+месяц|в\s+прошлом\s+месяце|последн\w*\s+месяц", tl):
        return _last_month()

    if re.search(r"последн\w*\s+недел|прошл\w*\s+недел|на\s+прошлой\s+неделе", tl):
        return _last_week()

    days_match = re.search(r"последни\w*\s+(\d+)\s+дн", tl)
    if days_match:
        return (_fmt(today - timedelta(days=int(days_match.group(1)))), _fmt(today))

    if "позавчера" in tl:
        d = _fmt(today - timedelta(days=2))
        return (d, d)
    if "вчера" in tl:
        d = _fmt(today - timedelta(days=1))
        return (d, d)
    if "сегодня" in tl:
        d = _fmt(today)
        return (d, d)

    range_match = re.search(
        r"с\s+(\d{1,2})\s+по\s+(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?",
        tl,
    )
    if range_match:
        d1, d2 = int(range_match.group(1)), int(range_match.group(2))
        month = MONTHS_RU_TO_NUM.get(range_match.group(3), 0)
        year = range_match.group(4) or str(today.year)
        if month:
            return (f"{year}-{month:02d}-{d1:02d}", f"{year}-{month:02d}-{d2:02d}")

    # -- English relative dates --
    if "last year" in tl:
        y = today.year - 1
        return (_fmt(datetime(y, 1, 1)), _fmt(datetime(y, 12, 31)))
    if "last month" in tl:
        return _last_month()
    if "last week" in tl:
        return _last_week()
    if "yesterday" in tl:
        d = _fmt(today - timedelta(days=1))
        return (d, d)
    if "today" in tl:
        d = _fmt(today)
        return (d, d)
    en_days = re.search(r"last\s+(\d+)\s+days?", tl)
    if en_days:
        return (_fmt(today - timedelta(days=int(en_days.group(1)))), _fmt(today))

    # -- Weekday (RU) --
    for day_name, day_num in DAYS_RU.items():
        if day_name in tl and ("прошл" in tl or "последн" in tl):
            back = (today.weekday() - day_num) % 7 or 7
            d = _fmt(today - timedelta(days=back))
            return (d, d)

    # -- Weekday (EN) --
    for day_name, day_num in DAYS_EN.items():
        if day_name in tl and "last" in tl:
            back = (today.weekday() - day_num) % 7 or 7
            d = _fmt(today - timedelta(days=back))
            return (d, d)

    return None


# -- Helpers -----------------------------------------------------------------


def get_dates_in_range(start_date: str, end_date: str) -> list[str]:
    """Generate a list of ISO dates between *start_date* and *end_date* (inclusive)."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates
