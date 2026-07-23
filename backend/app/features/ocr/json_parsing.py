import json
import re

_CODE_FENCE_START_RE = re.compile(r"^```json\s*", re.IGNORECASE)
_CODE_FENCE_START_PLAIN_RE = re.compile(r"^```\s*")
_CODE_FENCE_END_RE = re.compile(r"\s*```$")
_CONTROL_CHARS_IN_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def strip_markdown(text: str) -> str:
    text = _CODE_FENCE_START_RE.sub("", text)
    text = _CODE_FENCE_START_PLAIN_RE.sub("", text)
    text = _CODE_FENCE_END_RE.sub("", text)
    return text.strip()


def sanitize_json(text: str) -> str:
    def _clean_match(match: re.Match) -> str:
        def _replace_char(c: re.Match) -> str:
            char = c.group(0)
            return _ESCAPES.get(char, "")

        return re.sub(r"[\x00-\x1f\x7f]", _replace_char, match.group(0))

    return _CONTROL_CHARS_IN_STRING_RE.sub(_clean_match, text)


def parse_extraction_json(raw: str) -> dict:
    cleaned = sanitize_json(strip_markdown(raw))
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(cleaned)
        if not match:
            raise ValueError("AI returned invalid JSON") from None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return json.loads(sanitize_json(match.group(0)))
