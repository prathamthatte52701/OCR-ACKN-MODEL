"""Upload file-name handling shared by documents and chat attachments."""

import re
import unicodedata
from pathlib import PurePosixPath

NO_USABLE_NAME_MESSAGE = "This file has no usable name. Rename it and try again."


def base_name(raw: str | None) -> str:
    """The file name only: no path (either separator), no control or bidi characters, whitespace
    collapsed. This is the first half of the chat attachment name cleaner."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf", "Zl", "Zp"))
    return re.sub(r"\s+", " ", name).strip()


def has_usable_name(raw: str | None) -> bool:
    """False for a name that cleans to nothing: empty, spaces, only dots, only separators."""
    return bool(base_name(raw).strip(". "))
