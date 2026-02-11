"""Date extraction and parsing utilities (RU + EN).

Supports ISO, relative expressions, and named weekdays.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()

# -- Month / weekday lookup tables ------------------------------------------

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
MONTHS_RU_TO_NUM = {v: k for k, v in MONTHS_RU.items()}

MONTHS_EN = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}
MONTHS_EN_TO_NUM = {v: k for k, v in MONTHS_EN.items()}

DAYS_RU = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2,
    "четверг": 3, "пятница": 4, "пятницу": 4,
    "суббота": 5, "субботу": 5, "воскресенье": 6,
}

DAYS_EN = {
    "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}

# -- Single-date extraction -------------------------------------------------

def extract_date_from_text(text: str) -> Optional[str]:  # TODO: async migration
    """Extract a single ISO date (YYYY-MM-DD) from *text*.

    Supports ISO (``2025-12-25``), Russian (``25 декабря 2025``),
    and English (``December 25, 2025`` / ``25 December 2025``) formats.

    Returns:
        ISO date string or ``None``.
    """
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if iso_match:
        return iso_match.group(1)

    ru_date = re.search(
        r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?',
        text, re.IGNORECASE,
    )
    if ru_date:
        day = int(ru_date.group(1))
        month = MONTHS_RU_TO_NUM.get(ru_date.group(2).lower(), 0)
        year = ru_date.group(3) or "2025"
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    en_date1 = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?(?:[,\s]+(\d{4}))?',
        text, re.IGNORECASE,
    )
    if en_date1:
        month = MONTHS_EN_TO_NUM.get(en_date1.group(1).lower(), 0)
        day = int(en_date1.group(2))
        year = en_date1.group(3) or "2025"
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    en_date2 = re.search(
        r'(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?',
        text, re.IGNORECASE,
    )
    if en_date2:
        day = int(en_date2.group(1))
        month = MONTHS_EN_TO_NUM.get(en_date2.group(2).lower(), 0)
        year = en_date2.group(3) or "2025"
        if month:
            return f"{year}-{month:02d}-{day:02d}"

    return None

# -- Date-range extraction ---------------------------------------------------

def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def extract_date_range(text: str) -> Optional[Tuple[str, str]]:  # TODO: async migration
    """Extract a date range from *text*.

    Supports relative expressions in Russian and English (``last week``,
    ``yesterday``, ``последние 7 дней``, etc.) and explicit ranges
    like ``с 20 по 26 декабря``.

    Returns:
        ``(start_date, end_date)`` in ISO format, or ``None``.
    """
    tl = text.lower()
    today = datetime.now()

    # -- Russian relative dates --
    if re.search(r'прошл\w*\s+год|в\s+прошлом\s+году|последн\w*\s+год', tl):
        y = today.year - 1
        return (_fmt(datetime(y, 1, 1)), _fmt(datetime(y, 12, 31)))

    if re.search(r'прошл\w*\s+месяц|в\s+прошлом\s+месяце|последн\w*\s+месяц', tl):
        first_cur = today.replace(day=1)
        last_prev = first_cur - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return (_fmt(first_prev), _fmt(last_prev))

    if re.search(r'последн\w*\s+недел|прошл\w*\s+недел', tl):
        return (_fmt(today - timedelta(days=7)), _fmt(today))

    days_match = re.search(r'последни\w*\s+(\d+)\s+дн', tl)
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
        r'с\s+(\d{1,2})\s+по\s+(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?',
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
        first_cur = today.replace(day=1)
        last_prev = first_cur - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return (_fmt(first_prev), _fmt(last_prev))
    if "last week" in tl:
        return (_fmt(today - timedelta(days=7)), _fmt(today))
    if "yesterday" in tl:
        d = _fmt(today - timedelta(days=1))
        return (d, d)
    if "today" in tl:
        d = _fmt(today)
        return (d, d)
    en_days = re.search(r'last\s+(\d+)\s+days?', tl)
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

def get_dates_in_range(start_date: str, end_date: str) -> List[str]:
    """Generate a list of ISO dates between *start_date* and *end_date* (inclusive)."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates: List[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates
