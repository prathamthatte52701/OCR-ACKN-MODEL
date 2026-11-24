"""PyMuPDF prints "The `fitz` API is deprecated ... Use `import pymupdf` instead." on `import fitz`.
The code must import `pymupdf` (same library, same version) and nothing may import `fitz`."""

import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
_FITZ_IMPORT = re.compile(r"^\s*(import|from)\s+fitz\b", re.MULTILINE)


def test_no_python_file_imports_fitz() -> None:
    offenders = [
        str(p.relative_to(BACKEND))
        for p in BACKEND.rglob("*.py")
        if "venv" not in p.parts
        and p != Path(__file__).resolve()
        and _FITZ_IMPORT.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == [], offenders


def test_importing_the_pdf_modules_prints_no_fitz_notice() -> None:
    code = (
        "import app.core.image_limits, app.features.ocr.preprocessing, "
        "app.features.documents.router, app.main; print('imported')"
    )
    out = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", code],
        cwd=BACKEND,
        env={**os.environ, "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    text = out.stdout + out.stderr
    assert out.returncode == 0 and "imported" in out.stdout, text[-600:]
    assert "fitz" not in text.lower(), text[-600:]
