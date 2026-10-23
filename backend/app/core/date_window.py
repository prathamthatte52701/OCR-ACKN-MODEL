"""Plausibility window for a paper's own DD/MM/YYYY date. Neutral home so ocr/ and excel/ can agree
without importing each other (excel/service.py::document_period applies the same window; a parity
test keeps the two in step)."""

import re
from datetime import date, timedelta

MAX_FUTURE_DAYS = 1
MAX_PAST_YEARS = 5

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def date_implausible(date_str: str | None, today: date) -> bool:
    """True only for a REAL DD/MM/YYYY date outside the window (more than MAX_FUTURE_DAYS ahead of
    `today`, more than MAX_PAST_YEARS back, or in a future year). Missing/unreal -> False."""
    match = _DATE_RE.match(date_str) if isinstance(date_str, str) else None
    if not match:
        return False
    try:
        parsed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return False
    try:
        oldest = today.replace(year=today.year - MAX_PAST_YEARS)
    except ValueError:  # 29 Feb minus N years
        oldest = today.replace(year=today.year - MAX_PAST_YEARS, day=28)
    plausible = (
        oldest <= parsed <= today + timedelta(days=MAX_FUTURE_DAYS) and parsed.year <= today.year
    )
    return not plausible
