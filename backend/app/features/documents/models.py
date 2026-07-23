from datetime import datetime
from typing import Literal

from app.core.base_model import MongoBaseModel
from app.core.object_id import PyObjectId


class Document(MongoBaseModel):
    user_id: PyObjectId
    auto_name: str
    original_filename: str
    mime_type: str
    size: int
    grid_fs_file_id: PyObjectId | None = None
    upload_status: Literal["uploaded", "processed", "failed"] = "uploaded"
    # User-selected at upload time, not AI-guessed.
    document_type: Literal["Tax Invoice", "Delivery Challan"]

    # Tax Invoice has two number fields (box number + separate Reference No.);
    # Delivery Challan has just one. Unused fields for a given type stay null.
    tax_invoice_no: str | None = None
    reference_no: str | None = None
    number: str | None = None
    date: str | None = None  # DD/MM/YYYY

    # 0-100, null = no extraction attempted yet. AI-uncertainty signal, not a
    # per-field OCR-engine score.
    tax_invoice_no_confidence: float | None = None
    reference_no_confidence: float | None = None
    number_confidence: float | None = None
    date_confidence: float | None = None

    edited: bool = False
    ocr_text_hidden: str | None = None

    processing_error: str | None = None
    processed_at: datetime | None = None
    reprocessed_at: datetime | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None


class Workbook(MongoBaseModel):
    """One record per yearly Excel workbook, per user. Old workbooks are
    never deleted - rollover marks isActive False and sets archivedAt."""

    user_id: PyObjectId
    year: int
    filename: str
    is_active: bool = True
    archived_at: datetime | None = None


class Settings_(MongoBaseModel):
    """One 'excelState' row per user, tracking their currently active
    workbook. Named Settings_ to avoid clashing with app.core.config.Settings."""

    user_id: PyObjectId
    key: str
    active_workbook_name: str | None = None
    active_year: int | None = None


class ExportedRow(MongoBaseModel):
    """Audit trail of every export, independent of the Document/Excel file -
    survives document deletion/reprocessing."""

    document_id: PyObjectId
    user_id: PyObjectId
    workbook_id: PyObjectId | None = None
    document_type: str
    tax_invoice_no: str | None = None
    reference_no: str | None = None
    number: str | None = None
    date: str | None = None
    exported_at: datetime


class Correction(MongoBaseModel):
    document_id: PyObjectId
    field_label: str
    field_key: str
    old_value: str | None = None
    new_value: str
    corrected_at: datetime
