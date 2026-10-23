"""Every AI value is cleaned to str|None before any corrector sees it."""

import math
from typing import Any

import pytest
from loguru import logger

from app.features.ocr.ai_extraction import extract_header
from app.features.ocr.extraction import EXTRACTION_VALUE_FIELDS, build_extraction_result
from app.features.ocr.providers.base import AIProvider

TI, DC = "Tax Invoice", "Delivery Challan"
FIELDS = [(TI, "taxInvoiceNo"), (TI, "referenceNo"), (DC, "number")]
GOOD = {"taxInvoiceNo": "G0027704827", "referenceNo": "1234567890", "number": "820762791"}

# (id, raw value, expected stored value); "{good}" = a valid sample for that field
CASES: list[tuple[str, Any, Any]] = [
    ("str", "{good}", "{good}"),
    ("padded", "  {good}  ", "{good}"),
    ("empty", "", None),
    ("blank", "   ", None),
    ("65chars", "8" * 65, None),
    ("64chars", "8" * 64, "8" * 64),
    ("frac", 12.5, None),
    ("nan", math.nan, None),
    ("inf", math.inf, None),
    ("ninf", -math.inf, None),
    ("huge", 1e300, None),
    ("2**53", float(2**53), None),
    ("true", True, None),
    ("false", False, None),
    ("none", None, None),
    ("list", ["821234567"], None),
    ("emptylist", [], None),
    ("dict", {"v": "821234567"}, None),
    ("nested", [["8"], {"a": [1]}], None),
]


def _expand(value: Any, field: str) -> Any:
    return value.format(good=GOOD[field]) if isinstance(value, str) and "{good}" in value else value


@pytest.mark.parametrize(("doc_type", "field"), FIELDS)
@pytest.mark.parametrize(("name", "raw", "expected"), CASES, ids=[c[0] for c in CASES])
def test_value_fields(doc_type: str, field: str, name: str, raw: Any, expected: Any) -> None:
    result = build_extraction_result(doc_type, {field: _expand(raw, field), "date": "01/02/2026"})
    got = result[field]
    assert got == _expand(expected, field)
    assert got is None or isinstance(got, str)
    if got is None:
        assert result.get(f"{field}NeedsReview") is False


@pytest.mark.parametrize(("doc_type", "field"), FIELDS)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1234567890, "1234567890"), (1234567890.0, "1234567890"), (-5, "-5"), (0, "0")],
    ids=["int", "wholefloat", "negint", "zero"],
)
def test_numeric_reply_becomes_str(doc_type: str, field: str, raw: Any, expected: str) -> None:
    got = build_extraction_result(doc_type, {field: raw, "date": "01/02/2026"})[field]
    assert isinstance(got, str)
    # the digit-only corrector may leave it unchanged; it must at least be text of the digits
    assert got.lstrip("GP") == expected.lstrip("GP") or got == expected


@pytest.mark.parametrize("doc_type", [TI, DC])
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01/02/2026", "01/02/2026"),
        (" 01/02/2026 ", "01/02/2026"),
        ("", None),
        (20260102, None),
        (20260102.0, None),
        (["01/02/2026"], None),
        ({"d": "01/02/2026"}, None),
        (True, None),
        (None, None),
        ("9" * 65, None),
        ("31/02/2026", None),
        ("01/01/1999", None),
    ],
)
def test_date_field(doc_type: str, raw: Any, expected: Any) -> None:
    assert build_extraction_result(doc_type, {"date": raw})["date"] == expected


def test_int_number_goes_through_correctors() -> None:
    ok = build_extraction_result(DC, {"number": 820762791, "date": "01/02/2026"})
    assert ok["number"] == "820762791" and ok["numberNeedsReview"] is False
    short = build_extraction_result(DC, {"number": 82076279, "date": "01/02/2026"})
    assert short["number"] == "82076279" and short["numberNeedsReview"] is True


@pytest.mark.parametrize("doc_type", [TI, DC])
@pytest.mark.parametrize("parsed", [[], None, "text", 5, ["a"]])
def test_parsed_not_a_dict(doc_type: str, parsed: Any) -> None:
    result = build_extraction_result(doc_type, parsed)
    assert all(result.get(f) is None for f in EXTRACTION_VALUE_FIELDS)
    assert not any(v is True for v in result.values())


def test_warning_logged_without_the_value() -> None:
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="WARNING", format="{message}")
    try:
        build_extraction_result(DC, {"number": ["SECRETVALUE123"], "date": {"x": "SECRETDATE99"}})
        build_extraction_result(DC, {"number": "S" * 70})
        build_extraction_result(DC, {"number": True})
    finally:
        logger.remove(sink)
    text = "\n".join(lines)
    assert "number" in text and "list" in text and "date" in text and "dict" in text
    assert "SECRETVALUE123" not in text and "SECRETDATE99" not in text and "SSSS" not in text
    assert len(lines) == 4  # list number, dict date, 70-char number, bool number


class _Fake(AIProvider):
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def extract(self, system_prompt: str, user_prompt: str) -> str:
        return self.reply


async def test_end_to_end_int_number() -> None:
    result = await extract_header(
        TI, "hdr", provider=_Fake('{"taxInvoiceNo": 1234567890, "date": "01/02/2026"}')
    )
    assert isinstance(result["taxInvoiceNo"], str)


async def test_end_to_end_list_number() -> None:
    result = await extract_header(
        DC, "hdr", provider=_Fake('{"number": ["821234567"], "date": [20260102]}')
    )
    assert result["number"] is None and result["date"] is None
    assert result["numberNeedsReview"] is False


@pytest.mark.parametrize("raw", [20260102, 20260102.0, 5, True, ["01/02/2026"], {"d": 1}])
def test_only_a_str_ever_reaches_the_date_functions(
    monkeypatch: pytest.MonkeyPatch, raw: Any
) -> None:
    from app.features.ocr import extraction

    seen: list[Any] = []
    real_norm = extraction.normalize_date_to_ddmmyyyy
    real_fix = extraction.correct_date_format

    def spy_norm(v: Any) -> Any:
        seen.append(v)
        return real_norm(v)

    def spy_fix(v: Any) -> Any:
        seen.append(v)
        return real_fix(v)

    monkeypatch.setattr(extraction, "normalize_date_to_ddmmyyyy", spy_norm)
    monkeypatch.setattr(extraction, "correct_date_format", spy_fix)
    assert build_extraction_result(DC, {"date": raw})["date"] is None
    assert all(v is None or isinstance(v, str) for v in seen)
