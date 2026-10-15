"""The year/month the user sees (workbook year rollover, month fallback) follows IST, not the
server's own clock. Pure unit tests - no database."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.features.excel import service


class _FrozenNow:
    """datetime stand-in whose now(tz) returns a fixed UTC instant converted to tz."""

    instant = datetime(2026, 12, 31, 18, 45, tzinfo=UTC)  # = 2027-01-01 00:15 IST

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


def test_current_period_uses_ist_at_the_year_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import timezones

    monkeypatch.setattr(timezones, "datetime", _FrozenNow)
    assert service.current_period() == (2027, "January")  # UTC clock would say 2026 / December


def test_current_period_explicit_now_is_untouched() -> None:
    assert service.current_period(datetime(2026, 6, 30, 23, 59)) == (2026, "June")
