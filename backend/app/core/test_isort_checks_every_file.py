"""isort 9 cannot parse a source file with some non-ASCII characters when Python runs with
Windows' default encoding (cp1252): it prints "Unable to parse file ..." and SKIPS the file, exit
code 0, so a file with unsorted imports passes. In UTF-8 mode it parses everything. This test runs
isort in UTF-8 mode (-X utf8) so the import-order check really covers every file, whatever the
shell's encoding."""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def _isort(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "isort", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=250,
    )


def test_every_file_in_app_is_parsed_and_correctly_sorted() -> None:
    out = _isort("app", "--check-only")
    text = out.stdout + out.stderr
    assert "Unable to parse" not in text, text[-800:]
    assert out.returncode == 0, text[-800:]


def test_an_unsorted_non_ascii_file_is_flagged_not_skipped(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import sys\nimport os\n# café ٣\nx = 1\n", encoding="utf-8")
    out = _isort("--check-only", "--settings-path", str(BACKEND / "pyproject.toml"), str(bad))
    assert out.returncode == 1, out.stdout + out.stderr
    assert "incorrectly sorted" in out.stdout + out.stderr
