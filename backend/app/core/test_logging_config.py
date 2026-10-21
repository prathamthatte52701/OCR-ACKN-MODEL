"""Logging tests: file sink, idempotency, redaction, uvicorn intercept. No DB."""

import io
import logging
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from app.core import logging_config as lc

MONGO = "mongodb+srv://bob:s3cr3tPw@cluster0.abc.mongodb.net/db"
GSK = "gsk_AbCdEf0123456789XyZ"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VySWQiOiIxIn0.sig_nature-123"
SECRETS = ["s3cr3tPw", GSK, JWT, "hunter2", "abc.def.ghi-token", "topsecret"]
LEAKY = (
    f"uri {MONGO} key {GSK} Authorization: Bearer abc.def.ghi-token jwt {JWT} "
    "password=hunter2 {'password': 'hunter2'} "
    '{"password": "hunter2"} token="hunter2" JWT_SECRET=topsecret'
)


@pytest.fixture(autouse=True)
def clean_logging() -> Iterator[None]:
    yield
    logger.remove()
    lc._file_sink_id = None
    logger.configure(patcher=lambda r: None)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [h for h in lg.handlers if h is not lc._intercept_handler]
        lg.propagate = True
    logger.add(sys.stderr)


def _flush() -> None:
    logger.complete()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_file_sink_writes_utf8(tmp_path: Path) -> None:
    sid = lc.setup_file_sink(tmp_path / "sub dir")
    assert sid is not None
    logger.info("total \u20b9500 caf\u00e9")
    _flush()
    text = _read(tmp_path / "sub dir" / "app.log")
    assert "total \u20b9500 caf\u00e9" in text and " | INFO | " in text


def test_file_sink_idempotent(tmp_path: Path) -> None:
    lc.setup_file_sink(tmp_path)
    lc.setup_file_sink(tmp_path)
    logger.info("only-once")
    _flush()
    assert _read(tmp_path / "app.log").count("only-once") == 1


def test_configure_twice_no_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(lc, "LOG_DIR", tmp_path)
    lc.configure_logging()
    lc.configure_logging()
    logger.info("dup-check")
    _flush()
    assert _read(tmp_path / "app.log").count("dup-check") == 1
    assert capsys.readouterr().err.count("dup-check") == 1


def test_unwritable_folder_console_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", boom)
    assert lc.setup_file_sink(tmp_path / "nope") is None
    err = capsys.readouterr().err
    assert err.count("file logging is OFF") == 1


def test_open_failure_console_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real_add = logger.add

    def boom(sink: Any, *a: Any, **k: Any) -> Any:
        if isinstance(sink, Path):
            raise PermissionError("locked")
        return real_add(sink, *a, **k)

    monkeypatch.setattr(logger, "add", boom)
    assert lc.setup_file_sink(tmp_path) is None
    assert capsys.readouterr().err.count("file logging is OFF") == 1


def test_write_failure_never_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lc.setup_file_sink(tmp_path)

    def boom(self: Any, message: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("loguru._file_sink.FileSink.write", boom)
    logger.info("will fail to write")
    logger.complete()  # reaching here without an exception is the assertion


def test_rotation_creates_zip(tmp_path: Path) -> None:
    lc.setup_file_sink(tmp_path, rotation="2 KB", retention=5)
    for i in range(200):
        logger.info(f"line {i} " + "x" * 40)
    _flush()
    logger.remove()
    zips = list(tmp_path.glob("*.zip"))
    assert zips
    with zipfile.ZipFile(zips[0]) as z:
        assert z.namelist()
    assert (tmp_path / "app.log").exists()
    lc.setup_file_sink(tmp_path, rotation="2 KB", retention=5)
    logger.info("still-works")
    _flush()
    assert "still-works" in _read(tmp_path / "app.log")


@pytest.mark.parametrize(
    "text",
    [
        "Document processed for user bob@example.com in 12.5s",
        "Saved to E:\\ACKN OCR model\\backend\\app.core.logging_config.py",
        "Invoice 1234/2024 total 5,000 on 2024-03-01; tokenVersion=3 ok",
        "app.features.documents.router started",
    ],
)
def test_redact_leaves_ordinary_text(text: str) -> None:
    assert lc.redact(text) == text


def test_redact_masks_all_cases() -> None:
    out = lc.redact(LEAKY)
    for s in SECRETS:
        assert s not in out
    assert "mongodb+srv://" in out and "cluster0.abc.mongodb.net" in out
    assert "bob" not in out


def _sinks(tmp_path: Path) -> io.StringIO:
    lc.setup_file_sink(tmp_path)
    buf = io.StringIO()
    logger.add(buf, format="{message}")
    logger.configure(patcher=lc.redaction_patcher)
    return buf


def test_redaction_in_message_both_sinks(tmp_path: Path) -> None:
    lc.setup_file_sink(tmp_path)
    buf = io.StringIO()
    logger.add(buf, format="{message}")
    logger.configure(patcher=lc.redaction_patcher)
    logger.info(LEAKY)
    _flush()
    for text in (_read(tmp_path / "app.log"), buf.getvalue()):
        for s in SECRETS:
            assert s not in text
        assert "***" in text


def test_redaction_in_traceback_both_sinks(tmp_path: Path) -> None:
    buf = _sinks(tmp_path)
    try:
        raise RuntimeError(f"connect failed {MONGO} password=hunter2 {GSK}")
    except RuntimeError:
        logger.exception("boom")
    _flush()
    for text in (_read(tmp_path / "app.log"), buf.getvalue()):
        assert "RuntimeError" in text and "Traceback" in text
        for s in SECRETS:
            assert s not in text


def test_uvicorn_intercept(tmp_path: Path) -> None:
    lc.setup_file_sink(tmp_path)
    logger.configure(patcher=lc.redaction_patcher)
    lc.install_uvicorn_intercept()
    lc.install_uvicorn_intercept()
    logging.getLogger("uvicorn.error").error("uv-error password=hunter2")
    logging.getLogger("uvicorn").warning("uv-root")
    logging.getLogger("uvicorn.access").info("uv-access-line")
    _flush()
    text = _read(tmp_path / "app.log")
    assert text.count("uv-error") == 1 and "hunter2" not in text
    assert text.count("uv-root") == 1
    assert "uv-access-line" not in text
    assert logging.getLogger("uvicorn.error").propagate is False


def test_redact_review_gaps_are_closed() -> None:
    """Gaps an independent reviewer found: other Authorization schemes, escaped quotes, a raw '@'
    in a Mongo password, and more key names."""
    cases = {
        "Authorization: Basic dXNlcjpwYXNz": "dXNlcjpwYXNz",
        'headers={"authorization": "Digest abc123secret"}': "abc123secret",
        '{"password": "a\\"bSECRET"}': "bSECRET",
        "mongodb://bob:p@ssTAIL@host/db": "ssTAIL",
        "x-api-key: KEYVALUE12345": "KEYVALUE12345",
        "api-key=KEYVALUE67890": "KEYVALUE67890",
        "passwd=hunter2x": "hunter2x",
        "pwd=hunter3x": "hunter3x",
        "cookie: sessionid=COOKIEVAL": "COOKIEVAL",
    }
    for text, secret in cases.items():
        assert secret not in lc.redact(text), text
    plain = r"the token expired for user a@b.com at C:	empile.txt"
    assert lc.redact(plain) == plain
