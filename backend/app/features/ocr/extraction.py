"""Pure-Python validation layer - ported 1:1 from the old services/groq.js
post-processing (normalizeDateToDDMMYYYY plus the OCR character-confusion
corrections). No AI involved in this file."""

import re
from datetime import datetime

DATE_RE = re.compile(r"^(\d{2})[./-](\d{2})[./-](\d{4})$")
# A real TAX INVOICE No. always starts with "G" or "P" (e.g. G0027704827).
# This is a code-level safety net on top of the AI, not a replacement for it -
# a value that doesn't match is never silently accepted or auto-corrected.
TAX_INVOICE_NO_PREFIX_RE = re.compile(r"^[GP]")
TAX_INVOICE_NO_FORMAT_RE = re.compile(r"^[GP]\d+$")
ALL_DIGITS_RE = re.compile(r"^\d+$")
# Full shape of a Tax Invoice's own numbers (every real sample: G + 10 digits, 10-digit
# Reference No.). Only used to FLAG a value for review - never to change or reject it.
TAX_INVOICE_NO_FULL_RE = re.compile(r"^[GP]\d{10}$")
REFERENCE_NO_FULL_RE = re.compile(r"^\d{10}$")
# Delivery Challan No.: 9 digits starting "82" in every real sample (an Order number starts "27").
DELIVERY_CHALLAN_NO_FULL_RE = re.compile(r"^82\d{7}$")
DATE_CHARS_RE = re.compile(r"^[\d./-]+$")


# Classic OCR character-confusion pairs, letter -> the digit it's most often
# misread as. Deliberately narrow: only unambiguous, well-known confusions -
# never guessed. The Tax Invoice's own leading G/P is never run through this
# (see correct_number_format below), so "G" -> "6" only ever applies to a G
# appearing after position 0.
_CONFUSION_MAP = {
    "I": "1",
    "l": "1",
    "O": "0",
    "o": "0",
    "Z": "2",
    "z": "2",
    "S": "5",
    "s": "5",
    "B": "8",
    "b": "8",
    "G": "6",
    "g": "6",
    "D": "0",
    "d": "0",
}


def _apply_confusion_map(chars: list[str], allowed: set[str], start: int = 0) -> bool:
    """Mutates chars in place from index `start` onward, replacing any
    character that is neither already-allowed nor a known digit with its
    confusion-map digit equivalent. Returns whether anything changed."""
    changed = False
    for i in range(start, len(chars)):
        c = chars[i]
        if c in allowed or c.isdigit():
            continue
        mapped = _CONFUSION_MAP.get(c)
        if mapped is not None:
            chars[i] = mapped
            changed = True
    return changed


def correct_all_digits_format(value: str | None) -> tuple[str | None, bool]:
    """Post-extraction, pure-rule-based correction pass for a field that is
    always plain digits with no letter prefix - Delivery Challan's `number`
    and Tax Invoice's `referenceNo` (both always numeric in every real
    document; only `taxInvoiceNo` has the G/P anchor, see
    correct_number_format below). Every character is corrected toward
    all-digits via the same confusion map, never invents a digit that isn't
    a clear character-confusion mapping.

    Returns (possibly-corrected value, was_auto_corrected). On any failure
    to reach a fully valid format, returns the ORIGINAL value unchanged and
    False - the caller keeps the value as extracted."""
    if not value or not isinstance(value, str):
        return value, False
    stripped = value.strip()
    if not stripped:
        return value, False
    chars = list(stripped)
    changed = _apply_confusion_map(chars, allowed=set())
    if not changed:
        return value, False
    corrected = "".join(chars)
    if ALL_DIGITS_RE.match(corrected):
        return corrected, True
    return value, False


def correct_number_format(value: str | None, document_type: str) -> tuple[str | None, bool]:
    """Post-extraction, pure-rule-based correction pass for the number field
    (extends the Phase 3 "G prefix" safety net - never calls the AI again,
    never invents a digit that isn't a clear character-confusion mapping).

    Tax Invoice: first character must already be G or P - that anchor is
    validated but NEVER auto-corrected; every character after it is
    corrected toward all-digits. Delivery Challan: delegates to
    correct_all_digits_format (every character corrected toward all-digits,
    no first-character exception).

    Returns (possibly-corrected value, was_auto_corrected). On any failure
    to reach a fully valid format, returns the ORIGINAL value unchanged and
    False - the caller keeps the value as extracted.
    """
    if not value or not isinstance(value, str):
        return value, False
    stripped = value.strip()
    if not stripped:
        return value, False

    if document_type == "Tax Invoice":
        if not TAX_INVOICE_NO_PREFIX_RE.match(stripped):
            return value, False
        chars = list(stripped)
        changed = _apply_confusion_map(chars, allowed=set(), start=1)
        if not changed:
            return value, False
        corrected = "".join(chars)
        if TAX_INVOICE_NO_FORMAT_RE.match(corrected):
            return corrected, True
        return value, False

    # Delivery Challan
    return correct_all_digits_format(value)


def correct_date_format(raw_date: str | None) -> tuple[str | None, bool]:
    """Same character-confusion correction, applied to the date field for
    both document types - digits and separators (. / -) only, no letters."""
    if not raw_date or not isinstance(raw_date, str):
        return raw_date, False
    stripped = raw_date.strip()
    if not stripped:
        return raw_date, False
    chars = list(stripped)
    changed = _apply_confusion_map(chars, allowed=set("./-"))
    if not changed:
        return raw_date, False
    corrected = "".join(chars)
    if DATE_CHARS_RE.match(corrected):
        return corrected, True
    return raw_date, False


def normalize_date_to_ddmmyyyy(raw: str | None) -> str | None:
    """Never guess: only accepts an already-unambiguous DD/MM/YYYY-shaped
    value (separator normalized to /). Anything else -> None."""
    if not raw or not isinstance(raw, str):
        return None
    match = DATE_RE.match(raw.strip())
    if not match:
        return None
    dd, mm, yyyy = match.groups()
    d, m, y = int(dd), int(mm), int(yyyy)
    # A real calendar date in a sane range: 31/02/2026 and 01/01/1900 used to
    # pass (only 1-31 / 1-12 were checked) and were filed into a made-up month.
    if not 2000 <= y <= 2100:
        return None
    try:
        datetime(y, m, d)
    except ValueError:
        return None
    return f"{dd}/{mm}/{yyyy}"


def _needs_review(value: str | None, full_shape: re.Pattern[str]) -> bool:
    """True for a value that was read but is not the full expected shape (a dropped or
    extra character). Flag only - the value itself is never touched."""
    return bool(value) and full_shape.match(str(value)) is None


def _corrected_date(raw_date: str | None) -> tuple[str | None, bool]:
    """Tries the raw date as-is first (the common case); only falls back to
    the character-correction pass if the raw value doesn't already parse -
    correction never overrides a value that was already unambiguous."""
    date = normalize_date_to_ddmmyyyy(raw_date)
    if date is not None:
        return date, False

    corrected_raw, was_corrected = correct_date_format(raw_date)
    if was_corrected:
        corrected_date = normalize_date_to_ddmmyyyy(corrected_raw)
        if corrected_date is not None:
            return corrected_date, True

    return None, False


def build_extraction_result(document_type: str, parsed: dict) -> dict:
    """Applies a deterministic rule-based correction pass for classic OCR
    character-confusion errors (e.g. a trailing "I" misread in place of "1")
    to a raw {taxInvoiceNo/number, referenceNo, date} dict already parsed from
    the AI response. Correction never invents digits - it only fixes a value
    that fails validation into one that passes, using an unambiguous
    letter-to-digit mapping; anything it can't resolve falls through
    unchanged."""
    date, date_auto_corrected = _corrected_date(parsed.get("date"))

    if document_type == "Tax Invoice":
        tax_invoice_no = parsed.get("taxInvoiceNo") or None
        corrected_tin, tin_auto_corrected = correct_number_format(tax_invoice_no, document_type)
        if tin_auto_corrected:
            tax_invoice_no = corrected_tin
        reference_no = parsed.get("referenceNo") or None
        corrected_ref, ref_auto_corrected = correct_all_digits_format(reference_no)
        if ref_auto_corrected:
            reference_no = corrected_ref

        return {
            "taxInvoiceNo": tax_invoice_no,
            "referenceNo": reference_no,
            "date": date,
            "taxInvoiceNoNeedsReview": _needs_review(tax_invoice_no, TAX_INVOICE_NO_FULL_RE),
            "referenceNoNeedsReview": _needs_review(reference_no, REFERENCE_NO_FULL_RE),
            "taxInvoiceNoAutoCorrected": tin_auto_corrected,
            "dateAutoCorrected": date_auto_corrected,
        }

    number = parsed.get("number") or None
    corrected_number, number_auto_corrected = correct_number_format(number, document_type)
    if number_auto_corrected:
        number = corrected_number

    return {
        "number": number,
        "date": date,
        "numberNeedsReview": _needs_review(number, DELIVERY_CHALLAN_NO_FULL_RE),
        "numberAutoCorrected": number_auto_corrected,
        "dateAutoCorrected": date_auto_corrected,
    }


def empty_extraction_result(document_type: str) -> dict:
    if document_type == "Tax Invoice":
        return {
            "taxInvoiceNo": None,
            "referenceNo": None,
            "date": None,
            "taxInvoiceNoNeedsReview": False,
            "referenceNoNeedsReview": False,
            "taxInvoiceNoAutoCorrected": False,
            "dateAutoCorrected": False,
        }
    return {
        "number": None,
        "date": None,
        "numberNeedsReview": False,
        "numberAutoCorrected": False,
        "dateAutoCorrected": False,
    }
