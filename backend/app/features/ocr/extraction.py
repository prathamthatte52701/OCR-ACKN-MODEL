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

# --- Raw-OCR-text plausibility checks -------------------------------------
#
# Shape validation above (PLAUSIBLE_NUMBER_RE/DATE_RE/TAX_INVOICE_NO_PREFIX_RE)
# only proves a value is well-formed - it can't tell a date pulled from the
# wrong table row from the right one, since both are syntactically valid
# dates. The checks below look at the raw OCR text (row-grouped by
# paddle_runner.py's run_ocr) to see whether the AI's answer plausibly came
# from the right place: same/adjacent line as its field's label. This is
# still a heuristic - it can't catch a single wrong digit that lands the
# value on a line it doesn't literally belong to - so it stays additive to
# the shape checks, never a replacement.
_SEPARATOR_CHARS_RE = re.compile(r"[./\-]")
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_REFERENCE_NO_LABEL_RE = re.compile(r"reference\s*no\.?", re.IGNORECASE)
_TAX_INVOICE_LABEL_RE = re.compile(r"tax\s*invoice", re.IGNORECASE)
_DELIVERY_CHALLAN_LABEL_RE = re.compile(r"delivery\s*challan", re.IGNORECASE)

# A value that fails the "found near its label" check is real-looking (it
# passed shape validation) but unverifiable against the OCR text - cap
# confidence well below the frontend's low-confidence threshold (80) rather
# than the misleading 100 it would otherwise get, but don't null the value
# out (we don't know a better one).
UNVERIFIED_VALUE_CONFIDENCE_CAP = 45.0
# PaddleOCR's own per-box recognition confidence (rec_scores). This engine's
# scores are typically 0.95+ on a clean scan; anything below this suggests
# the character recognition itself was shaky somewhere in the crop.
MIN_REC_SCORE_THRESHOLD = 0.85
LOW_REC_SCORE_CONFIDENCE_CAP = 60.0


def _digits_only(s: str) -> str:
    return _SEPARATOR_CHARS_RE.sub("", s)


def _alnum_only(s: str) -> str:
    return _NON_ALNUM_RE.sub("", s).upper()


def _date_verified(
    header_text: str | None, date_value: str | None, label_re: re.Pattern[str]
) -> bool:
    """True if date_value's digits (DD/MM/YYYY, separator-agnostic) appear on
    one of the header_text lines that also contains label_re - i.e. the same
    printed table row, post row-grouping (see paddle_runner.py's run_ocr,
    which assembles one text-detection row per printed row specifically so a
    label and its own value share a line).

    Deliberately NOT tolerant of adjacent lines: the diagnosed bug is the AI
    grabbing a date from a row that is structurally ADJACENT to "Reference
    No." (e.g. "Payment Due Date" sitting right above/below it in the
    source table) - an adjacent-line tolerance here would let that exact
    bug back in.

    No header_text (callers/tests that don't pass it) means "nothing to
    check against" -> treated as verified so this stays purely additive on
    top of the existing shape-based confidence, never a downgrade by
    default."""
    if not header_text or not header_text.strip():
        return True
    if not date_value:
        return False
    target = _digits_only(date_value)
    if not target:
        return False
    return any(
        target in _digits_only(line) for line in header_text.split("\n") if label_re.search(line)
    )


def _value_verified(header_text: str | None, value: str | None, label_re: re.Pattern[str]) -> bool:
    """True if value (alnum-only, case-insensitive) appears on a header_text
    line that also contains label_re - same reasoning as _date_verified
    above (same line only, no adjacent-line tolerance). No header_text ->
    treated as verified."""
    if not header_text or not header_text.strip():
        return True
    if not value:
        return False
    target = _alnum_only(value)
    if not target:
        return False
    return any(
        target in _alnum_only(line) for line in header_text.split("\n") if label_re.search(line)
    )


def _apply_plausibility_cap(
    confidence: float, verified: bool, cap: float = UNVERIFIED_VALUE_CONFIDENCE_CAP
) -> float:
    """Layers on top of shape-based confidence: never raises it, only caps it
    lower when the value couldn't be verified against the raw OCR text."""
    if confidence <= 0 or verified:
        return confidence
    return min(confidence, cap)


def _apply_rec_score_cap(confidence: float, min_rec_score: float | None) -> float:
    if confidence <= 0 or min_rec_score is None or min_rec_score >= MIN_REC_SCORE_THRESHOLD:
        return confidence
    return min(confidence, LOW_REC_SCORE_CONFIDENCE_CAP)


# Digit-count seen consistently across every real sample of this issuer's
# template - catches the OCR failure class none of the checks above can:
# a dropped or inserted digit (e.g. "9800539637" -> "980059337", or an extra
# trailing "0"), where every character is individually a valid digit so
# there is nothing to "correct", only something to flag. Length-only, never
# rejects/nulls/rewrites the value - a real value from a different vendor's
# template with a different digit count just gets downgraded to "please
# verify" instead of a false 100%, same soft-cap philosophy as
# _apply_plausibility_cap/_apply_rec_score_cap above. Date is deliberately
# NOT covered here - normalize_date_to_ddmmyyyy's DATE_RE already requires
# an exact DD/MM/YYYY digit count, so a dropped/inserted digit there already
# fails validation and returns None; a length check would add nothing.
EXPECTED_REFERENCE_NO_DIGITS = 10
EXPECTED_TAX_INVOICE_NO_DIGITS = 10  # digits after the leading G/P
EXPECTED_DELIVERY_CHALLAN_NO_DIGITS = 9
LENGTH_MISMATCH_CONFIDENCE_CAP = 50.0


def _digit_count_plausible(value: str | None, expected_digits: int) -> bool:
    """Counts digit characters only (not _digits_only - that helper strips
    date separators but leaves letters like the taxInvoiceNo's leading G/P
    in place, which would wrongly count toward length here). No
    header_text-style 'trust by default when we can't check' escape hatch -
    the value itself is all the input this check needs, so None/empty just
    isn't plausible rather than being treated as verified."""
    if not value:
        return False
    return sum(1 for c in value if c.isdigit()) == expected_digits


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
    False - the existing low-confidence flagging picks it up from there."""
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


def build_extraction_result(
    document_type: str,
    parsed: dict,
    header_text: str | None = None,
    min_rec_score: float | None = None,
) -> dict:
    """Applies validation/confidence scoring, then a deterministic rule-based
    correction pass for classic OCR character-confusion errors (e.g. a
    trailing "I" misread in place of "1"), to a raw {taxInvoiceNo/number,
    referenceNo, date} dict already parsed from the AI response. Correction
    never invents digits - it only fixes a value that fails validation into
    one that passes, using an unambiguous letter-to-digit mapping; anything
    it can't resolve falls through unchanged to the existing low-confidence
    flagging.

    header_text (the raw, row-grouped OCR text the AI saw - see
    paddle_runner.py's run_ocr) and min_rec_score (OCR's own lowest per-box
    recognition confidence) are optional so existing callers/tests that only
    have the parsed AI dict keep working; when present they additionally
    cross-check each value against the source text near its field's label
    and cap confidence when a value can't be verified there (see
    _date_verified/_value_verified above) - this is what catches a
    syntactically-valid-but-wrong-row date or a hallucinated number that the
    shape checks alone score as 100%."""
    date, date_conf, date_auto_corrected = _corrected_date(parsed.get("date"))

    if document_type == "Tax Invoice":
        tax_invoice_no = parsed.get("taxInvoiceNo") or None
        corrected_tin, tin_auto_corrected = correct_number_format(tax_invoice_no, document_type)
        if tin_auto_corrected:
            tax_invoice_no = corrected_tin
        reference_no = parsed.get("referenceNo") or None
        corrected_ref, ref_auto_corrected = correct_all_digits_format(reference_no)
        if ref_auto_corrected:
            reference_no = corrected_ref

        date_conf = _apply_plausibility_cap(
            date_conf, _date_verified(header_text, date, _REFERENCE_NO_LABEL_RE)
        )
        tin_conf = _apply_plausibility_cap(
            tax_invoice_no_confidence(tax_invoice_no),
            _value_verified(header_text, tax_invoice_no, _TAX_INVOICE_LABEL_RE),
        )
        ref_conf = _apply_plausibility_cap(
            number_confidence(reference_no),
            _value_verified(header_text, reference_no, _REFERENCE_NO_LABEL_RE),
        )
        tin_conf = _apply_plausibility_cap(
            tin_conf,
            _digit_count_plausible(tax_invoice_no, EXPECTED_TAX_INVOICE_NO_DIGITS),
            cap=LENGTH_MISMATCH_CONFIDENCE_CAP,
        )
        ref_conf = _apply_plausibility_cap(
            ref_conf,
            _digit_count_plausible(reference_no, EXPECTED_REFERENCE_NO_DIGITS),
            cap=LENGTH_MISMATCH_CONFIDENCE_CAP,
        )
        date_conf = _apply_rec_score_cap(date_conf, min_rec_score)
        tin_conf = _apply_rec_score_cap(tin_conf, min_rec_score)
        ref_conf = _apply_rec_score_cap(ref_conf, min_rec_score)

        return {
            "taxInvoiceNo": tax_invoice_no,
            "referenceNo": reference_no,
            "date": date,
            "taxInvoiceNoConfidence": tin_conf,
            "referenceNoConfidence": ref_conf,
            "dateConfidence": date_conf,
            "taxInvoiceNoAutoCorrected": tin_auto_corrected,
            "dateAutoCorrected": date_auto_corrected,
        }

    number = parsed.get("number") or None
    corrected_number, number_auto_corrected = correct_number_format(number, document_type)
    if number_auto_corrected:
        number = corrected_number

    date_conf = _apply_plausibility_cap(
        date_conf, _date_verified(header_text, date, _DELIVERY_CHALLAN_LABEL_RE)
    )
    number_conf = _apply_plausibility_cap(
        number_confidence(number), _value_verified(header_text, number, _DELIVERY_CHALLAN_LABEL_RE)
    )
    number_conf = _apply_plausibility_cap(
        number_conf,
        _digit_count_plausible(number, EXPECTED_DELIVERY_CHALLAN_NO_DIGITS),
        cap=LENGTH_MISMATCH_CONFIDENCE_CAP,
    )
    date_conf = _apply_rec_score_cap(date_conf, min_rec_score)
    number_conf = _apply_rec_score_cap(number_conf, min_rec_score)

    return {
        "number": number,
        "date": date,
        "numberConfidence": number_conf,
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
