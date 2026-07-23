"""Smoke test for the Phase 3 validation module + its OCR-correction pass.
Run directly: python -m app.features.ocr.test_extraction"""

from app.features.ocr.extraction import (
    build_extraction_result,
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


def demo() -> None:
    test_tax_invoice_number_confusion_corrected()
    test_delivery_challan_number_confusion_corrected()
    test_date_confusion_corrected()
    test_unmappable_character_falls_back_to_low_confidence()
    test_leading_g_never_auto_corrected()
    test_invalid_first_character_not_guessed_between_g_and_p()
    test_build_extraction_result_end_to_end_tax_invoice()
    test_build_extraction_result_end_to_end_delivery_challan()
    print("All extraction/correction self-checks passed.")


if __name__ == "__main__":
    demo()
