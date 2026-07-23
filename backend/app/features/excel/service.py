import asyncio
import os
import re
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

EXPORT_DIR = Path(__file__).resolve().parents[3] / "exports"
HEADERS = ["Document Type", "Number", "Date", "Timestamp"]
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# All workbook writes are serialized through this lock - two concurrent saves
# would otherwise read-modify-write the same file and lose a row. Ported from
# the old app's _writeChain promise-chain serialization.
# ponytail: single global lock serializes ALL users' exports, not just same-
# file ones - fine at this scale, upgrade to a per-filename lock if export
# volume ever makes that a bottleneck.
_write_lock = asyncio.Lock()


class FileLockedError(Exception):
    pass


def _ensure_export_dir() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def file_path(filename: str) -> Path:
    # No path traversal via a user-supplied filename.
    safe = os.path.basename(filename)
    if not safe.endswith(".xlsx"):
        safe = f"{safe}.xlsx"
    return EXPORT_DIR / safe


def current_period(now: datetime | None = None) -> tuple[int, str]:
    now = now or datetime.now()
    return now.year, MONTHS[now.month - 1]


def month_from_date(date_str: str | None, fallback_now: datetime | None = None) -> str:
    """Worksheet month comes from the DOCUMENT'S OWN extracted date, not
    today's date - a document dated 30/06 always lands in the June sheet
    even if saved in July. Falls back to the current month if unparseable."""
    if date_str:
        match = _DATE_RE.match(date_str)
        if match:
            mm = int(match.group(2))
            if 1 <= mm <= 12:
                return MONTHS[mm - 1]
    return current_period(fallback_now)[1]


def _add_header_row(sheet: Worksheet) -> None:
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = openpyxl.styles.Font(bold=True)


def _create_workbook_sync(filename: str, month: str) -> Path:
    _ensure_export_dir()
    workbook = openpyxl.Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    sheet = workbook.create_sheet(month)
    _add_header_row(sheet)
    target = file_path(filename)
    tmp_target = target.with_suffix(f".tmp{os.getpid()}.xlsx")
    try:
        workbook.save(tmp_target)
        os.replace(tmp_target, target)
    except PermissionError as exc:
        tmp_target.unlink(missing_ok=True)
        raise FileLockedError(
            f'"{target.name}" is open in Excel. Close it and try saving again.'
        ) from exc
    except Exception:
        tmp_target.unlink(missing_ok=True)
        raise
    return target


async def create_workbook(filename: str, month: str | None = None) -> Path:
    month = month or current_period()[1]
    return await asyncio.to_thread(_create_workbook_sync, filename, month)


def _format_number_cell(row: dict) -> str | None:
    if row["documentType"] == "Tax Invoice":
        parts = [p for p in (row.get("taxInvoiceNo"), row.get("referenceNo")) if p]
        return " / ".join(parts) if parts else None
    return row.get("number") or None


def _append_row_sync(filename: str, month: str, row: dict) -> Path:
    _ensure_export_dir()
    target = file_path(filename)
    if not target.exists():
        # Settings can point at a file that was deleted from disk - recreate it.
        _create_workbook_sync(filename, month)

    # Write to a temp file and swap it in with os.replace, rather than
    # openpyxl.save(target) directly - if the target is locked open elsewhere
    # (e.g. Excel), a direct save can truncate the file before the lock error
    # surfaces, corrupting it for every save after the lock is released.
    tmp_target = target.with_suffix(f".tmp{os.getpid()}.xlsx")
    try:
        workbook = openpyxl.load_workbook(target)
        if month in workbook.sheetnames:
            sheet = workbook[month]
        else:
            sheet = workbook.create_sheet(month)
            _add_header_row(sheet)
        sheet.append([row["documentType"], _format_number_cell(row), row["date"], row["timestamp"]])
        workbook.save(tmp_target)
        os.replace(tmp_target, target)
    except PermissionError as exc:
        tmp_target.unlink(missing_ok=True)
        raise FileLockedError(
            f'"{target.name}" is open in Excel. Close it and try saving again.'
        ) from exc
    except Exception:
        tmp_target.unlink(missing_ok=True)
        raise
    return target


async def append_row(filename: str, month: str, row: dict) -> Path:
    async with _write_lock:
        return await asyncio.to_thread(_append_row_sync, filename, month, row)
