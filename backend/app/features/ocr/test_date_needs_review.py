"""dateNeedsReview: a real but implausible date is flagged (never changed)."""

from datetime import date, datetime, timedelta

import pytest

from app.core.date_window import date_implausible
from app.features.documents.correction import correction_set_fields
from app.features.excel.service import document_period
from app.features.ocr import extraction as ex
from app.features.ocr.extraction import build_extraction_result, empty_extraction_result

TODAY = date(2026, 6, 15)


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15/06/2026", False),
        ("16/06/2026", False),  # today + 1
        ("17/06/2026", True),  # today + 2
        ("15/06/2021", False),  # exactly 5 years back
        ("14/06/2021", True),  # 5 years back - 1 day
        ("16/06/2021", False),
        ("01/01/2027", True),  # future year
        ("32/13/2026", False),  # unreal -> not flagged
        (None, False),
    ],
)
def test_flag_in_build_result(value: str | None, expected: bool) -> None:
    for doc_type, key in (("Tax Invoice", "taxInvoiceNo"), ("Delivery Challan", "number")):
        r = build_extraction_result(doc_type, {key: "X", "date": value}, today=TODAY)
        assert r["dateNeedsReview"] is expected
        if expected:
            assert r["date"] == value  # value never changed
    assert empty_extraction_result("Tax Invoice")["dateNeedsReview"] is False
    assert empty_extraction_result("Delivery Challan")["dateNeedsReview"] is False


def test_flag_in_flag_fields_and_correction() -> None:
    assert "dateNeedsReview" in ex.EXTRACTION_FLAG_FIELDS
    assert (
        correction_set_fields("date", "01/01/2099", datetime(2026, 1, 1))["dateNeedsReview"]
        is False
    )
    assert "dateNeedsReview" not in correction_set_fields("number", "1", datetime(2026, 1, 1))


def test_parity_with_document_period() -> None:
    todays = [date(2026, 6, 15), date(2024, 2, 29), date(2026, 12, 31), date(2026, 1, 1)]
    for today in todays:
        now = datetime(today.year, today.month, today.day, 12)
        probes: set[date] = set()
        for base in (today, today.replace(day=28)):
            for dy in (0, 1, 5, 6):
                try:
                    anchor = base.replace(year=base.year - dy)
                except ValueError:
                    anchor = base.replace(year=base.year - dy, day=28)
                probes.update(anchor + timedelta(days=n) for n in (-2, -1, 0, 1, 2))
        probes.update(
            {date(today.year + 1, 1, 1), date(today.year, 12, 31), date(today.year, 2, 28)}
        )
        for p in probes:
            s = _fmt(p)
            assert date_implausible(s, today) is (not document_period(s, now)[2]), (today, s)
