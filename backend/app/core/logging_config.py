import inspect
import logging
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from loguru import logger

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
_file_sink_id: int | None = None

_KEYS = (
    r"password(?:Hash)?|passwd|pwd|token|secret|authorization|api[-_]?key|cookie"
    r"|JWT_SECRET|MONGO_URI"
)
# Known gap (documented, not fixed): an UNQUOTED secret that itself contains spaces is only masked
# up to its first space ("password: my secret phrase"); quoted values are masked whole.
_PATTERNS: list[tuple[re.Pattern[str], Any]] = [
    # Greedy up to the LAST @ of the token, so a raw "@" inside the password cannot leak its tail.
    (re.compile(r"(mongodb(?:\+srv)?://)[^/\s:@]+:\S*@", re.I), r"\1***@"),
    (re.compile(r"gsk_[A-Za-z0-9_-]+"), "gsk_***"),
    (re.compile(r"(Bearer\s+)[^\s\"',;]+", re.I), r"\1***"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "***jwt***"),
    # "Authorization: Basic <b64>" / Digest ...: mask the scheme word AND the credential.
    (re.compile(r"""(authorization["']?\s*[:=]\s*)(?:\w+\s+)?[^\s,;}&"']+""", re.I), r"\1***"),
    (
        re.compile(
            rf"""((?:{_KEYS})["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}}&]+)""",
            re.I,
        ),
        lambda m: m.group(1)
        + (m.group(2)[0] if m.group(2)[0] in "\"'" else "")
        + "***"
        + (m.group(2)[0] if m.group(2)[0] in "\"'" else ""),
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redaction_patcher(record: Any) -> None:
    """Redact message AND traceback (rendered here since sinks format exceptions themselves)."""
    msg = record["message"]
    exc = record["exception"]
    if exc is not None:
        tb = "".join(traceback.format_exception(exc.type, exc.value, exc.traceback))
        msg = f"{msg}\n{tb.rstrip()}"
        record["exception"] = None
    record["message"] = redact(msg)


def setup_file_sink(
    log_dir: Path | None = None,
    rotation: str | int = "10 MB",
    retention: str | int = "10 days",
    compression: str = "zip",
    level: str = "INFO",
) -> int | None:
    """Add the rotating file sink; never raises. Replaces any sink this helper added earlier."""
    global _file_sink_id
    if _file_sink_id is not None:
        try:
            logger.remove(_file_sink_id)
        except ValueError:
            pass
        _file_sink_id = None
    folder = log_dir or LOG_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _file_sink_id = logger.add(
            folder / "app.log",
            level=level,
            format=_FORMAT,
            rotation=rotation,
            retention=retention,
            compression=compression,
            encoding="utf-8",
            enqueue=True,
            catch=True,
        )
    except Exception as exc:  # noqa: BLE001 - logging must never stop the app
        print(f"file logging is OFF: {exc}", file=sys.stderr)
        return None
    return _file_sink_id


class _InterceptHandler(logging.Handler):
    """Stdlib -> loguru bridge (from the loguru docs)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


_intercept_handler = _InterceptHandler()


def install_uvicorn_intercept() -> None:
    """uvicorn / uvicorn.error only; uvicorn.access is left alone."""
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [_intercept_handler]
        lg.propagate = False


def configure_logging() -> None:
    logger.remove()
    global _file_sink_id
    _file_sink_id = None
    logger.configure(patcher=redaction_patcher)
    logger.add(sys.stderr, level="INFO", format=_FORMAT)
    setup_file_sink()
    install_uvicorn_intercept()
