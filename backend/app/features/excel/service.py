import asyncio
import os
import re
import threading
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import openpyxl
from filelock import FileLock
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.worksheet.worksheet import Worksheet

from app.core.timezones import now_ist

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

# A paper's own date is trusted for the workbook year/month only inside this window (IST today):
# a misread year (2052, 2005) must never create a stray workbook for the wrong year.
MAX_FUTURE_DAYS = 1
MAX_PAST_YEARS = 5

# Workbook writes are serialized per physical filename, two-layer:
#   1. An asyncio.Lock keyed by filename - cheap, sub-millisecond, handles the
#      common case (multiple concurrent requests within this one process).
#   2. An OS-level FileLock (filelock package) on a sidecar .lock file -
#      handles the rarer but real case of two backend processes somehow
#      bound to the same port at once (happened during dev testing here),
#      where two independent asyncio.Lock instances in two processes cannot
#      see each other and would otherwise silently interleave read-modify-
#      write cycles, dropping rows. Per-filename (not global) so saves to
#      different users'/years' workbooks never wait on each other.
_locks_guard = threading.Lock()
_write_locks: dict[str, asyncio.Lock] = {}


def _get_write_lock(filename: str) -> asyncio.Lock:
    with _locks_guard:
        lock = _write_locks.get(filename)
        if lock is None:
            lock = asyncio.Lock()
            _write_locks[filename] = lock
        return lock


class FileLockedError(Exception):
    pass


def _ensure_export_dir() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# Characters that can steer a path (or are invalid in Windows file names). A
# user-chosen workbook name containing "/" used to survive into the physical
# name, and file_path()'s os.path.basename() then threw away everything
# before it - including the owner's userId prefix - so "x/<victimId>_Bills"
# resolved to ANOTHER user's workbook (overwrite on create, unlink on user
# delete). Neutralizing them here keeps the prefix intact for every caller.
_UNSAFE_NAME_CHARS = re.compile(r'[\/:*?"<>|\x00-\x1f]')


def physical_workbook_filename(user_id: object, filename: str) -> str:
    """Single source of truth for the on-disk name of a user's workbook:
    `{userId}_{display name}` with path-steering characters neutralized.
    Ordinary names are unchanged, so existing files keep resolving."""
    safe = _UNSAFE_NAME_CHARS.sub("_", str(filename)).replace("..", "_")
    return f"{user_id}_{safe}"


def file_path(filename: str) -> Path:
    # No path traversal via a user-supplied filename.
    safe = os.path.basename(filename)
    if not safe.endswith(".xlsx"):
        safe = f"{safe}.xlsx"
    return EXPORT_DIR / safe


def current_period(now: datetime | None = None) -> tuple[int, str]:
    # IST, not the server clock: the year/month a user sees rolls over at IST midnight.
    now = now or now_ist()
    return now.year, MONTHS[now.month - 1]


def _parse_ddmmyyyy(date_str: str | None) -> date | None:
    match = _DATE_RE.match(date_str) if isinstance(date_str, str) else None
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:  # 32/12/2025, 31/02/2026, year 0
        return None


def document_period(date_str: str | None, today: datetime | None = None) -> tuple[int, str, bool]:
    """(year, month name, used_document_date): the ONE place that decides which workbook year and
    worksheet a document belongs to. The paper's own DD/MM/YYYY date decides both, so a paper dated
    Dec 2025 saved in Jan 2026 still goes to the 2025 workbook. A missing, unreal or implausible
    date (outside MAX_PAST_YEARS back .. MAX_FUTURE_DAYS ahead of today in IST) falls back to the
    save date in IST and reports used_document_date=False."""
    today_date = (today or now_ist()).date()
    parsed = _parse_ddmmyyyy(date_str)
    if parsed is not None:
        try:
            oldest = today_date.replace(year=today_date.year - MAX_PAST_YEARS)
        except ValueError:  # 29 Feb minus N years
            oldest = today_date.replace(year=today_date.year - MAX_PAST_YEARS, day=28)
        # never a future YEAR (a 1 Jan paper on 31 Dec): the next year's workbook is only ever
        # created by the user's own rollover prompt, so such a paper takes the save-date fallback
        if (
            oldest <= parsed <= today_date + timedelta(days=MAX_FUTURE_DAYS)
            and parsed.year <= today_date.year
        ):
            return parsed.year, MONTHS[parsed.month - 1], True
    return today_date.year, MONTHS[today_date.month - 1], False


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


def _lock_path(target: Path) -> Path:
    return target.with_suffix(".lock")


def _create_workbook_sync(filename: str, month: str) -> Path:
    """Assumes the caller already holds this filename's cross-process
    FileLock - does not acquire it itself, so it can be called both
    standalone (via _create_workbook_locked_sync) and inline from inside
    _append_row_sync's own lock without a reentrant/nested acquisition."""
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


def _create_workbook_locked_sync(filename: str, month: str) -> Path:
    _ensure_export_dir()
    target = file_path(filename)
    with FileLock(str(_lock_path(target)), timeout=30):
        return _create_workbook_sync(filename, month)


async def create_workbook(filename: str, month: str | None = None) -> Path:
    month = month or current_period()[1]
    async with _get_write_lock(filename):
        return await asyncio.to_thread(_create_workbook_locked_sync, filename, month)


# Leading characters Excel/LibreOffice treat as the start of a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _clean_cell(value: object) -> object:
    """Strips characters XML cannot hold (a control character in a corrected
    value made openpyxl raise IllegalCharacterError, i.e. a 500 on save)."""
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _force_text_cells(cells: tuple) -> None:
    """A value like =HYPERLINK("http://evil","x") or =cmd|' /C calc'!A0 was
    written as a LIVE formula (openpyxl infers one from a leading "="), and
    Export History lets other users download this workbook - classic
    spreadsheet formula injection. Anything starting like a formula is stored
    as a plain string cell instead, so it displays as text and never runs."""
    for cell in cells:
        if isinstance(cell.value, str) and cell.value.startswith(_FORMULA_PREFIXES):
            cell.data_type = "s"


def _format_number_cell(row: dict) -> str | None:
    if row["documentType"] == "Tax Invoice":
        parts = [p for p in (row.get("taxInvoiceNo"), row.get("referenceNo")) if p]
        return " / ".join(parts) if parts else None
    return row.get("number") or None


def _append_rows_sync(filename: str, items: list[tuple[str, dict]]) -> Path:
    _ensure_export_dir()
    target = file_path(filename)

    # Cross-process lock, held for the full read-modify-write below - closes
    # the gap an in-process-only asyncio.Lock leaves if two backend
    # processes ever end up bound to the same port (seen during dev here):
    # two independent asyncio.Lock instances can't see each other and would
    # otherwise let both processes load-modify-save concurrently, each
    # unaware of the other's write, silently dropping whichever row lost the
    # race to os.replace.
    with FileLock(str(_lock_path(target)), timeout=30):
        if not target.exists():
            # Settings can point at a file that was deleted from disk - recreate it.
            _create_workbook_sync(filename, items[0][0])

        # Write to a temp file and swap it in with os.replace, rather than
        # openpyxl.save(target) directly - if the target is locked open elsewhere
        # (e.g. Excel), a direct save can truncate the file before the lock error
        # surfaces, corrupting it for every save after the lock is released.
        tmp_target = target.with_suffix(f".tmp{os.getpid()}.xlsx")
        try:
            workbook = openpyxl.load_workbook(target)
            for month, row in items:
                if month in workbook.sheetnames:
                    sheet = workbook[month]
                else:
                    sheet = workbook.create_sheet(month)
                    _add_header_row(sheet)
                sheet.append(
                    [
                        _clean_cell(row["documentType"]),
                        _clean_cell(_format_number_cell(row)),
                        _clean_cell(row["date"]),
                        _clean_cell(row["timestamp"]),
                    ]
                )
                _force_text_cells(sheet[sheet.max_row])
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


def _append_row_sync(filename: str, month: str, row: dict) -> Path:
    return _append_rows_sync(filename, [(month, row)])


async def append_rows(filename: str, items: list[tuple[str, dict]]) -> Path:
    """Appends (month, row) items in order with ONE lock acquisition, ONE load and ONE save.
    Per-filename asyncio.Lock first (fast path, concurrent requests in this process); the
    FileLock inside _append_rows_sync is the second, cross-process layer. Keyed by filename (not
    global) so saves to different users'/years' workbooks never wait on each other."""
    if not items:
        return file_path(filename)
    async with _get_write_lock(filename):
        return await asyncio.to_thread(_append_rows_sync, filename, items)


async def append_row(filename: str, month: str, row: dict) -> Path:
    return await append_rows(filename, [(month, row)])


def row_key(row: dict) -> tuple[object, object, object]:
    """The (Document Type, Number, Date) tuple a worksheet row is matched by."""
    return (
        _clean_cell(row["documentType"]),
        _clean_cell(_format_number_cell(row)),
        _clean_cell(row.get("date")),
    )


Protect = tuple[str, tuple] | Mapping[tuple[str, tuple], int]


def _protect_counts(protect: Protect | None) -> Mapping[tuple[str, tuple], int]:
    if protect is None:
        return {}
    if isinstance(protect, tuple):
        return {protect: 1}
    return protect


def _delete_matching(workbook: Any, rows: list[dict], protect: Protect | None) -> list[bool]:
    """Deletes from `workbook` the rows matching `rows` (multiset by (sheet, key)) and returns, per
    requested row in the order given, whether a sheet row was found for it (the first records of a
    key get the found rows). protect = (sheet, key) or {(sheet, key): count}: the LAST `count`
    rows of that sheet matching key are the rows just appended and are never removed."""
    by_sheet: dict[str, dict[tuple, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, row in enumerate(rows):
        # the sheet the row was actually filed under (stored on the export record at save time);
        # older records fall back to the date's own month
        sheet_name = row.get("worksheet") or month_from_date(row.get("date"))
        by_sheet[sheet_name][row_key(row)].append(i)

    protected = _protect_counts(protect)
    found = [False] * len(rows)
    for sheet_name, wanted in by_sheet.items():
        if sheet_name not in workbook.sheetnames:
            continue
        sheet = workbook[sheet_name]
        matches: dict[tuple, list[int]] = defaultdict(list)
        for row_cells in sheet.iter_rows(min_row=2):
            key = (row_cells[0].value, row_cells[1].value, row_cells[2].value)
            if key in wanted:
                matches[key].append(row_cells[0].row)
        rows_to_delete: list[int] = []
        for key, idxs in wanted.items():
            found_rows = matches.get(key, [])
            n = min(len(idxs), max(0, len(found_rows) - protected.get((sheet_name, key), 0)))
            rows_to_delete.extend(found_rows[:n])
            for i in idxs[:n]:
                found[i] = True
        for idx in sorted(rows_to_delete, reverse=True):
            sheet.delete_rows(idx)
    return found


def _save_workbook_atomic(workbook: Any, target: Path) -> None:
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


def _remove_rows_core(
    filename: str,
    rows_to_remove: list[dict],
    keep_file: bool,
    protect: Protect | None,
) -> tuple[int, bool, list[bool]]:
    """Surgically deletes specific rows rather than rewriting the whole file.
    Rows have no stable ID (see _append_rows_sync), so matching is by the same
    (Document Type, Number, Date) tuple _format_number_cell already produces
    for the Number column - grouped per sheet as a multiset, not a
    set, because "Save Again" can legitimately append more than one identical
    row for the same document, and only as many rows as are actually being
    purged should come out, not every row that happens to match. Within a
    sheet, matched rows are deleted bottom-most-index-first so an earlier
    delete_rows() call never shifts the index of a row still pending
    deletion. Returns (rows_removed, workbook_is_now_fully_empty, found-per-requested-row).
    keep_file=True (Save Again replacing a row) never deletes the file even when it ends up
    without data rows.
    protect=(sheet, key) or {(sheet, key): count}: the LAST row(s) of that sheet matching `key`
    are never removed - they are the rows just appended, identical to the old one, and must
    survive even when the old row is gone."""
    target = file_path(filename)
    if not target.exists() or not rows_to_remove:
        return 0, False, [False] * len(rows_to_remove)

    fully_empty = False
    # Cross-process lock, same as _append_rows_sync - a concurrent save/remove
    # against this same physical file must never interleave with this
    # read-modify-write.
    with FileLock(str(_lock_path(target)), timeout=30):
        if not target.exists():
            return 0, False, [False] * len(rows_to_remove)
        workbook = openpyxl.load_workbook(target)
        found = _delete_matching(workbook, rows_to_remove, protect)
        fully_empty = all(sheet.max_row <= 1 for sheet in workbook.worksheets)
        if not fully_empty or keep_file:
            _save_workbook_atomic(workbook, target)

    # Unlink AFTER the FileLock context exits, not inside it - on Windows a
    # file with an open handle (the lock file itself, held by this same
    # process for the `with` block above) cannot be deleted while that
    # handle is still open.
    if fully_empty and not keep_file:
        target.unlink(missing_ok=True)
        _lock_path(target).unlink(missing_ok=True)

    return sum(found), fully_empty, found


def _remove_rows_sync(
    filename: str,
    rows_to_remove: list[dict],
    keep_file: bool = False,
    protect: Protect | None = None,
) -> tuple[int, bool]:
    removed, fully_empty, _ = _remove_rows_core(filename, rows_to_remove, keep_file, protect)
    return removed, fully_empty


async def remove_rows(
    filename: str,
    rows_to_remove: list[dict],
    keep_file: bool = False,
    protect: Protect | None = None,
) -> tuple[int, bool]:
    async with _get_write_lock(filename):
        return await asyncio.to_thread(
            _remove_rows_sync, filename, rows_to_remove, keep_file, protect
        )


async def remove_rows_detailed(
    filename: str, rows_to_remove: list[dict], protect: Protect | None = None
) -> list[bool]:
    """One load/save for many records (keep_file semantics, the file is never deleted). Returns,
    per requested record in the order given, whether its row was found and removed."""
    async with _get_write_lock(filename):
        _, _, found = await asyncio.to_thread(
            _remove_rows_core, filename, rows_to_remove, True, protect
        )
        return found
