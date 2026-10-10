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


def test_unmappable_character_left_unchanged() -> None:
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
    assert result["dateAutoCorrected"] is False


def test_build_extraction_result_end_to_end_delivery_challan() -> None:
    result = build_extraction_result(
        "Delivery Challan", {"number": "82026O534", "date": "O1/07/2O26"}
    )
    assert result["number"] == "820260534"
    assert result["numberAutoCorrected"] is True
    assert result["date"] == "01/07/2026"
    assert result["dateAutoCorrected"] is True


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


def demo() -> None:
    test_tax_invoice_number_confusion_corrected()
    test_delivery_challan_number_confusion_corrected()
    test_date_confusion_corrected()
    test_unmappable_character_left_unchanged()
    test_leading_g_never_auto_corrected()
    test_invalid_first_character_not_guessed_between_g_and_p()
    test_build_extraction_result_end_to_end_tax_invoice()
    test_build_extraction_result_end_to_end_delivery_challan()
    test_build_extraction_result_reference_no_confusion_corrected()
    test_results_carry_no_confidence_keys()
    test_wrong_length_tax_invoice_numbers_are_flagged_not_changed()
    test_well_formed_and_missing_numbers_are_not_flagged()
    print("All extraction/correction self-checks passed.")


def test_results_carry_no_confidence_keys() -> None:
    from app.features.ocr.extraction import empty_extraction_result

    for doc_type in ("Tax Invoice", "Delivery Challan"):
        for result in (
            build_extraction_result(doc_type, {"number": "820260534", "date": "01/07/2026"}),
            empty_extraction_result(doc_type),
        ):
            assert not [k for k in result if k.endswith("Confidence")]


def test_wrong_length_tax_invoice_numbers_are_flagged_not_changed() -> None:
    # Real OCR misreads: an extra "0" on the Tax Invoice No, a dropped digit on the Reference No.
    flagged = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G00277053700", "referenceNo": "980039537", "date": "10/07/2026"},
    )
    assert flagged["taxInvoiceNo"] == "G00277053700" and flagged["referenceNo"] == "980039537"
    assert flagged["taxInvoiceNoNeedsReview"] is True
    assert flagged["referenceNoNeedsReview"] is True


def test_well_formed_and_missing_numbers_are_not_flagged() -> None:
    ok = build_extraction_result(
        "Tax Invoice",
        {"taxInvoiceNo": "G0027705370", "referenceNo": "9800601391", "date": "10/07/2026"},
    )
    assert ok["taxInvoiceNoNeedsReview"] is False and ok["referenceNoNeedsReview"] is False
    missing = build_extraction_result("Tax Invoice", {})
    assert missing["taxInvoiceNoNeedsReview"] is False
    assert missing["referenceNoNeedsReview"] is False
    assert "taxInvoiceNoNeedsReview" not in build_extraction_result(
        "Delivery Challan", {"number": "12", "date": "10/07/2026"}
    )


if __name__ == "__main__":
    demo()
