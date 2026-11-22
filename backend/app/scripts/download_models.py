"""Downloads the OCR models once, so the first document is not slow.

    cd backend
    ..\venv\Scripts\python.exe -m app.scripts.download_models

It builds the OCR engine exactly like the app does (the same models, from OCR_DET_MODEL and
OCR_REC_MODEL, default PP-OCRv6 small), which downloads them into the PaddleX cache folder
(<user>\.paddlex\official_models, or PADDLE_PDX_CACHE_HOME if set). Nothing else is changed.
Exit code 0 = the models are ready, 1 = they could not be downloaded or loaded (reason printed).
"""

import os
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.features.ocr.paddle_runner import _load_ocr, short_error_message


def cache_folder() -> Path:
    base = os.environ.get("PADDLE_PDX_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".paddlex") / "official_models"


def main() -> int:
    print(f"OCR detection model  : {settings.ocr_det_model}")
    print(f"OCR recognition model: {settings.ocr_rec_model}")
    print(f"Saved in             : {cache_folder()}")
    source = os.environ.get("PADDLE_PDX_MODEL_SOURCE")
    print(f"Download source      : {source or 'default (Hugging Face)'}")
    print("Downloading and loading the models (about 30 MB the first time)...")
    started = time.monotonic()
    try:
        _load_ocr()
    except Exception as exc:  # noqa: BLE001 - one clear message, no traceback
        why = f"{type(exc).__name__}: {short_error_message(exc)}"
        print(f"ERROR: the OCR models could not be downloaded or loaded: {why}")
        print("Check the internet connection and the model names in backend/.env")
        print("(OCR_DET_MODEL, OCR_REC_MODEL).")
        print("They will be tried again the first time a document is read. See the README, section")
        print("'OCR models: download, offline and rollback' for a PC without internet.")
        return 1
    print(f"OK: the OCR models are ready ({time.monotonic() - started:.0f} s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
