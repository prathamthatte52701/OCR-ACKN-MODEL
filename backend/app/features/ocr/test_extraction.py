"""Smoke test for the Phase 3 validation module + its OCR-correction pass.
Run directly: python -m app.features.ocr.test_extraction"""

from app.features.ocr.extraction import (
    build_extraction_result,
    correct_all_digits_format,
    correct_date_format,
    correct_number_format,
)


def test_tax_invoice_number_confusion_corrected() -> None:
    corrected, was_corrected = correct_number_format("G002770482I", "Tax Invoice")
    assert was_corrected is True
    assert corrected == "G0027704821"


def test_delivery_challan_number_confusion_corrected() -> None:
    corrected, was_corrected = correct_number_format("82026O534", "Delivery Challan")
    assert was_corrected is True
    assert corrected == "820260534"


def test_date_confusion_corrected() -> None:
    corrected, was_corrected = correct_date_format("O1/07/2O26")
    assert was_corrected is True
    assert corrected == "01/07/2026"


def test_unmappable_character_falls_back_to_low_confidence() -> None:
    # '#' is not in the confusion map - never guessed, left unchanged.
    corrected, was_corrected = correct_number_format("G00277#482", "Tax Invoice")
    assert was_corrected is False
    assert corrected == "G00277#482"


def test_leading_g_never_auto_corrected() -> None:
    # The Tax Invoice's own leading G is a fixed anchor, not a confusable char.
    corrected, was_corrected = correct_number_format("G002770482", "Tax Invoice")
    assert was_corrected is False
    assert corrected == "G002770482"


def test_invalid_first_character_not_guessed_between_g_and_p() -> None:
    corrected, was_corrected = correct_number_format("X002770482", "Tax Invoice")
    assert was_corrected is False
    assert corrected == "X002770482"


def test_build_extraction_result_end_to_end_tax_invoice() -> None:
    result = build_extraction_result(
        "Tax Invoice", {"taxInvoiceNo": "G002770482I", "referenceNo": "REF1", "date": "01/07/2026"}
    )
    assert result["taxInvoiceNo"] == "G0027704821"
    assert result["taxInvoiceNoAutoCorrected"] is True
    assert result["taxInvoiceNoConfidence"] == 100.0
    assert result["dateAutoCorrected"] is False


def test_build_extraction_result_end_to_end_delivery_challan() -> None:
    result = build_extraction_result(
        "Delivery Challan", {"number": "82026O534", "date": "O1/07/2O26"}
    )
    assert result["number"] == "820260534"
    assert result["numberAutoCorrected"] is True
    assert result["date"] == "01/07/2026"
    assert result["dateAutoCorrected"] is True


# --- header_text cross-validation (wrong-row / hallucination bug fix) -----


def test_build_extraction_result_no_header_text_keeps_old_behavior() -> None:
    # header_text is optional - callers/tests that don't pass it (like the
    # end-to-end tests above) must keep getting pure shape-based confidence,
    # never a plausibility downgrade they have no way to satisfy.
    result = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027704827", "referenceNo": "9800532362", "date": "02/05/2026"},
    )
    assert result["dateConfidence"] == 100.0
    assert result["taxInvoiceNoConfidence"] == 100.0
    assert result["referenceNoConfidence"] == 100.0


def test_build_extraction_result_wrong_row_date_downgraded() -> None:
    # Reproduces the diagnosed bug: the AI grabbed a real date from the
    # header text, but from a "Payment Due Date" row, not the "Reference
    # No." row it was told to use. Both dates are syntactically valid, so
    # shape validation alone scores this 100 - the plausibility check must
    # catch the AI's answer not being adjacent to its own label's line.
    header_text = (
        "TAX INVOICE  G0027704827\n"
        "Payment Due Date  15.08.2026\n"
        "Reference No.  9800532362  02.05.2026\n"
    )
    result = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027704827", "referenceNo": "9800532362", "date": "15/08/2026"},
        header_text,
    )
    # Value is kept as-is - never guessed - only confidence is downgraded.
    assert result["date"] == "15/08/2026"
    assert result["dateConfidence"] <= 45.0


def test_build_extraction_result_correct_row_date_not_downgraded() -> None:
    header_text = (
        "TAX INVOICE  G0027704827\n"
        "Payment Due Date  15.08.2026\n"
        "Reference No.  9800532362  02.05.2026\n"
    )
    result = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027704827", "referenceNo": "9800532362", "date": "02/05/2026"},
        header_text,
    )
    assert result["date"] == "02/05/2026"
    assert result["dateConfidence"] == 100.0


def test_build_extraction_result_hallucinated_reference_no_downgraded() -> None:
    # referenceNo doesn't appear anywhere near "Reference No." in the OCR
    # text at all - a different failure mode (hallucination), also must not
    # be left at 100.
    header_text = "TAX INVOICE  G0027704827\nReference No.  9800532362  02.05.2026\n"
    result = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027704827", "referenceNo": "1234567890", "date": "02/05/2026"},
        header_text,
    )
    assert result["referenceNo"] == "1234567890"
    assert result["referenceNoConfidence"] <= 45.0


def test_build_extraction_result_delivery_challan_wrong_row_number_downgraded() -> None:
    header_text = "Sales Order  555555555\nDelivery Challan  820268362  10.07.2026\n"
    result = build_extraction_result(
        "Delivery Challan", {"number": "555555555", "date": "10/07/2026"}, header_text
    )
    assert result["number"] == "555555555"
    assert result["numberConfidence"] <= 45.0


def test_build_extraction_result_reference_no_confusion_corrected() -> None:
    # referenceNo previously never ran through the confusion-map correction
    # pass at all (only taxInvoiceNo/number did) - "O" here should be
    # corrected to "0" via correct_all_digits_format, same as it already is
    # for taxInvoiceNo/number.
    result = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027704827", "referenceNo": "98OO532362", "date": "02.05.2026"},
    )
    assert result["referenceNo"] == "9800532362"
    assert correct_all_digits_format("98OO532362") == ("9800532362", True)


def test_build_extraction_result_low_rec_score_caps_confidence() -> None:
    # OCR's own recognition confidence was shaky (well below the 0.85
    # threshold) even though the value passed both shape and plausibility
    # checks - confidence must still be capped.
    header_text = "TAX INVOICE  G0027704827\nReference No.  9800532362  02.05.2026\n"
    result = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027704827", "referenceNo": "9800532362", "date": "02/05/2026"},
        header_text,
        min_rec_score=0.5,
    )
    assert result["dateConfidence"] <= 60.0
    assert result["taxInvoiceNoConfidence"] <= 60.0
    assert result["referenceNoConfidence"] <= 60.0


def demo() -> None:
    test_tax_invoice_number_confusion_corrected()
    test_delivery_challan_number_confusion_corrected()
    test_date_confusion_corrected()
    test_unmappable_character_falls_back_to_low_confidence()
    test_leading_g_never_auto_corrected()
    test_invalid_first_character_not_guessed_between_g_and_p()
    test_build_extraction_result_end_to_end_tax_invoice()
    test_build_extraction_result_end_to_end_delivery_challan()
    test_build_extraction_result_no_header_text_keeps_old_behavior()
    test_build_extraction_result_wrong_row_date_downgraded()
    test_build_extraction_result_correct_row_date_not_downgraded()
    test_build_extraction_result_hallucinated_reference_no_downgraded()
    test_build_extraction_result_delivery_challan_wrong_row_number_downgraded()
    test_build_extraction_result_reference_no_confusion_corrected()
    test_build_extraction_result_low_rec_score_caps_confidence()
    print("All extraction/correction self-checks passed.")


if __name__ == "__main__":
    demo()
