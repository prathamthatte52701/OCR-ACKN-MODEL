"""Truth table of the "number is blank" rule. The frontend helper isNumberBlank() in
frontend/src/utils/documentDisplay.js implements the SAME table - change both together.

Delivery Challan: blank when `number` is empty/whitespace/missing.
Tax Invoice: blank only when BOTH taxInvoiceNo and referenceNo are empty/whitespace/missing."""

import pytest

from app.features.excel.router import _number_is_blank

TI = "Tax Invoice"
DC = "Delivery Challan"


@pytest.mark.parametrize(
    ("doc", "blank"),
    [
        ({"documentType": DC, "number": ""}, True),
        ({"documentType": DC, "number": "   "}, True),
        ({"documentType": DC, "number": None}, True),
        ({"documentType": DC}, True),
        ({"documentType": DC, "number": "8300001"}, False),
        ({"documentType": DC, "number": "x", "taxInvoiceNo": "INV1"}, False),
        ({"documentType": DC, "number": "", "taxInvoiceNo": "INV1"}, True),
        ({"documentType": TI, "taxInvoiceNo": " ", "referenceNo": ""}, True),
        ({"documentType": TI, "taxInvoiceNo": None, "referenceNo": None}, True),
        ({"documentType": TI}, True),
        ({"documentType": TI, "taxInvoiceNo": "INV1", "referenceNo": ""}, False),
        ({"documentType": TI, "taxInvoiceNo": "", "referenceNo": "REF1"}, False),
        ({"documentType": TI, "taxInvoiceNo": "", "referenceNo": "", "number": "9"}, True),
    ],
)
def test_number_is_blank_truth_table(doc: dict, blank: bool) -> None:
    assert _number_is_blank(doc) is blank
