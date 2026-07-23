"""Pure-Python validation/confidence layer - ported 1:1 from the old
services/groq.js post-processing (normalizeDateToDDMMYYYY, numberConfidence,
dateConfidence, taxInvoiceNoConfidence). No AI involved in this file."""

import re

DATE_RE = re.compile(r"^(\d{2})[./-](\d{2})[./-](\d{4})$")
PLAUSIBLE_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/-]{2,}$")
# A real TAX INVOICE No. always starts with "G" or "P" (e.g. G0027704827).
# This is a code-level safety net on top of the AI, not a replacement for it -
# a value that doesn't match is never silently accepted or auto-corrected,
# just downgraded below the frontend's low-confidence threshold (80).
TAX_INVOICE_NO_PREFIX_RE = re.compile(r"^[GP]")
TAX_INVOICE_NO_FORMAT_RE = re.compile(r"^[GP]\d+$")
ALL_DIGITS_RE = re.compile(r"^\d+$")
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


def correct_number_format(value: str | None, document_type: str) -> tuple[str | None, bool]:
    """Post-extraction, pure-rule-based correction pass for the number field
    (extends the Phase 3 "G prefix" safety net - never calls the AI again,
    never invents a digit that isn't a clear character-confusion mapping).

    Tax Invoice: first character must already be G or P - that anchor is
    validated but NEVER auto-corrected; every character after it is
    corrected toward all-digits. Delivery Challan: every character is
    corrected toward all-digits, no first-character exception.

    Returns (possibly-corrected value, was_auto_corrected). On any failure
    to reach a fully valid format, returns the ORIGINAL value unchanged and
    False - the existing low-confidence flagging picks it up from there.
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
    chars = list(stripped)
    changed = _apply_confusion_map(chars, allowed=set())
    if not changed:
        return value, False
    corrected = "".join(chars)
    if ALL_DIGITS_RE.match(corrected):
        return corrected, True
    return value, False


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
    d, m = int(dd), int(mm)
    if d < 1 or d > 31 or m < 1 or m > 12:
        return None
    return f"{dd}/{mm}/{yyyy}"


def number_confidence(value: str | None) -> float:
    if not value:
        return 0
    return 100.0 if PLAUSIBLE_NUMBER_RE.match(value.strip()) else 40.0


def date_confidence(raw_date: str | None, normalized_date: str | None) -> float:
    if not raw_date:
        return 0
    return 100.0 if normalized_date else 30.0


def tax_invoice_no_confidence(value: str | None) -> float:
    base = number_confidence(value)
    if base == 0:
        return 0
    return base if value and TAX_INVOICE_NO_PREFIX_RE.match(value.strip()) else 20.0


def _corrected_date(raw_date: str | None) -> tuple[str | None, float, bool]:
    """Tries the raw date as-is first (the common case); only falls back to
    the character-correction pass if the raw value doesn't already parse -
    correction never overrides a value that was already unambiguous."""
    date = normalize_date_to_ddmmyyyy(raw_date)
    if date is not None:
        return date, date_confidence(raw_date, date), False

    corrected_raw, was_corrected = correct_date_format(raw_date)
    if was_corrected:
        corrected_date = normalize_date_to_ddmmyyyy(corrected_raw)
        if corrected_date is not None:
            return corrected_date, date_confidence(corrected_raw, corrected_date), True

    return None, date_confidence(raw_date, None), False


def build_extraction_result(document_type: str, parsed: dict) -> dict:
    """Applies validation/confidence scoring, then a deterministic rule-based
    correction pass for classic OCR character-confusion errors (e.g. a
    trailing "I" misread in place of "1"), to a raw {taxInvoiceNo/number,
    referenceNo, date} dict already parsed from the AI response. Correction
    never invents digits - it only fixes a value that fails validation into
    one that passes, using an unambiguous letter-to-digit mapping; anything
    it can't resolve falls through unchanged to the existing low-confidence
    flagging."""
    date, date_conf, date_auto_corrected = _corrected_date(parsed.get("date"))

    if document_type == "Tax Invoice":
        tax_invoice_no = parsed.get("taxInvoiceNo") or None
        corrected_tin, tin_auto_corrected = correct_number_format(tax_invoice_no, document_type)
        if tin_auto_corrected:
            tax_invoice_no = corrected_tin
        reference_no = parsed.get("referenceNo") or None
        return {
            "taxInvoiceNo": tax_invoice_no,
            "referenceNo": reference_no,
            "date": date,
            "taxInvoiceNoConfidence": tax_invoice_no_confidence(tax_invoice_no),
            "referenceNoConfidence": number_confidence(reference_no),
            "dateConfidence": date_conf,
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
        "numberConfidence": number_confidence(number),
        "dateConfidence": date_conf,
        "numberAutoCorrected": number_auto_corrected,
        "dateAutoCorrected": date_auto_corrected,
    }


def empty_extraction_result(document_type: str) -> dict:
    if document_type == "Tax Invoice":
        return {
            "taxInvoiceNo": None,
            "referenceNo": None,
            "date": None,
            "taxInvoiceNoConfidence": 0,
            "referenceNoConfidence": 0,
            "dateConfidence": 0,
            "taxInvoiceNoAutoCorrected": False,
            "dateAutoCorrected": False,
        }
    return {
        "number": None,
        "date": None,
        "numberConfidence": 0,
        "dateConfidence": 0,
        "numberAutoCorrected": False,
        "dateAutoCorrected": False,
    }
