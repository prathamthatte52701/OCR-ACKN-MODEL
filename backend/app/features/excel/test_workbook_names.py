import pytest
from pydantic import ValidationError

from app.features.excel import service
from app.features.excel.schemas import NewExcelFileRequest

VICTIM = "6a65070f76dc9f20e037dee4"
ATTACKER = "6a65070f76dc9f20e037dee5"


def test_traversal_name_cannot_reach_another_users_file() -> None:
    evil = f"x/{VICTIM}_Bills"
    attacker_file = service.file_path(service.physical_workbook_filename(ATTACKER, evil))
    victim_file = service.file_path(service.physical_workbook_filename(VICTIM, "Bills"))
    assert attacker_file != victim_file
    assert attacker_file.name.startswith(f"{ATTACKER}_")


@pytest.mark.parametrize(
    "name",
    ["..\\..\\x", "a/b", "a\\b", "..", "x:y", "a|b", "n\x00ul", "dot.", "q" * 101, "   "],
)
def test_bad_workbook_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        NewExcelFileRequest(filename=name)


@pytest.mark.parametrize(
    "name", ["Bills_2026", "My Bills 2026", "invoices-2026.v2", "बिल 2026", "a" * 100]
)
def test_normal_workbook_names_still_work(name: str) -> None:
    assert NewExcelFileRequest(filename=name).filename == name.strip()
    assert service.physical_workbook_filename(VICTIM, name) == f"{VICTIM}_{name}"


def test_legacy_stored_traversal_name_is_neutralized() -> None:
    legacy = service.physical_workbook_filename(ATTACKER, f"x/{VICTIM}_Bills")
    assert "/" not in legacy and "\\" not in legacy
    assert legacy.startswith(f"{ATTACKER}_")
