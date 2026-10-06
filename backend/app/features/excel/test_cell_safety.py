from pathlib import Path
from typing import Any

import openpyxl
import pytest

from app.features.excel import service


def _append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: str) -> Any:
    monkeypatch.setattr(service, "EXPORT_DIR", tmp_path)
    row = {
        "documentType": "Delivery Challan",
        "number": number,
        "taxInvoiceNo": None,
        "referenceNo": None,
        "date": "01/07/2026",
        "timestamp": "2026-07-01T00:00:00Z",
    }
    path = service._append_row_sync("t_book", "July", row)
    sheet = openpyxl.load_workbook(path)["July"]
    return sheet[sheet.max_row][1]


def test_formula_text_is_stored_as_text_not_a_formula(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for evil in [
        '=HYPERLINK("http://evil.test","x")',
        "=cmd|' /C calc'!A0",
        "+1+1",
        "-2+3",
        "@SUM(A1)",
    ]:
        cell = _append(tmp_path, monkeypatch, evil)
        assert cell.data_type != "f", evil
        assert cell.value == evil


def test_control_characters_do_not_crash_the_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _append(tmp_path, monkeypatch, "A\x01B\x07C").value == "ABC"


def test_normal_number_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _append(tmp_path, monkeypatch, "820310006").value == "820310006"
