"""India Standard Time as a FIXED offset (no DST in India). A fixed offset instead of ZoneInfo on
purpose: ZoneInfo("Asia/Kolkata") needs the `tzdata` package on Windows. Every calendar day or month
boundary that a user or admin sees (they all see IST) must be built from this, never from UTC."""

from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
IST_OFFSET_STRING = "+05:30"  # for MongoDB $dateToString timezone


def now_ist() -> datetime:
    """The current moment as an aware IST datetime."""
    return datetime.now(IST)


def ist_midnight_utc(day: datetime) -> datetime:
    """UTC instant when the IST calendar day of `day` starts (a naive `day` is read as IST)."""
    local = day.astimezone(IST) if day.tzinfo else day.replace(tzinfo=IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
