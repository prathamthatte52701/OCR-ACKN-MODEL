import pytest

from app.features.ocr.extraction import normalize_date_to_ddmmyyyy


@pytest.mark.parametrize(
    "raw",
    [
        "31/02/2026",
        "31.04.2026",
        "00/01/2026",
        "01/13/2026",
        "01/01/1900",
        "13/09/3026",
        "29/02/2027",
    ],
)
def test_impossible_dates_are_rejected(raw: str) -> None:
    assert normalize_date_to_ddmmyyyy(raw) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("14.05.2026", "14/05/2026"),
        ("29/02/2028", "29/02/2028"),
        ("01-07-2026", "01/07/2026"),
        ("31/12/2100", "31/12/2100"),
    ],
)
def test_real_dates_still_normalize(raw: str, expected: str) -> None:
    assert normalize_date_to_ddmmyyyy(raw) == expected
