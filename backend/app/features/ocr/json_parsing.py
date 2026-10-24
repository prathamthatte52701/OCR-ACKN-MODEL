import json
import re

_CODE_FENCE_START_RE = re.compile(r"^```json\s*", re.IGNORECASE)
_CODE_FENCE_START_PLAIN_RE = re.compile(r"^```\s*")

_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def strip_markdown(text: str) -> str:
    text = _CODE_FENCE_START_RE.sub("", text)
    text = _CODE_FENCE_START_PLAIN_RE.sub("", text)
    # Closing fence at the very end. (The regex \s*```$ is quadratic on long whitespace.) The old
    # "$" also matched just before ONE trailing newline, so that newline is looked past.
    body = text[:-1] if text.endswith("\n") else text
    if body.endswith("```"):
        text = body[:-3] + text[len(body) :]
    return text.strip()


def sanitize_json(text: str) -> str:
    """Escapes control characters inside every well-formed "..." string: a quote, then any
    characters other than quote and backslash, or backslash + any non-newline character, then a
    closing quote. Same result as the regex '"((?:[^"\\\\]|\\\\.)*)"' but linear: the closing
    quote reachable from each position is worked out once, right to left, instead of being
    re-scanned for every opening quote."""
    n = len(text)
    end = [-1] * (n + 2)  # end[p]: closing-quote index of a string body starting at p, or -1
    for p in range(n - 1, -1, -1):
        c = text[p]
        if c == '"':
            end[p] = p
        elif c == "\\":
            end[p] = end[p + 2] if p + 1 < n and text[p + 1] != "\n" else -1
        else:
            end[p] = end[p + 1]

    def _replace_char(c: re.Match) -> str:
        return _ESCAPES.get(c.group(0), "")

    out: list[str] = []
    pos = 0
    i = 0
    while True:
        q = text.find('"', i)
        if q == -1:
            break
        e = end[q + 1]
        if e == -1:
            i = q + 1
            continue
        out.append(text[pos:q])
        out.append(re.sub(r"[\x00-\x1f\x7f]", _replace_char, text[q : e + 1]))
        pos = i = e + 1
    out.append(text[pos:])
    return "".join(out)


def parse_extraction_json(raw: str) -> dict:
    cleaned = sanitize_json(strip_markdown(raw))
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # From the first "{" to the last "}" (the span of the old regex \{[\s\S]*\}, found in
        # linear time).
        start, last = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or last <= start:
            raise ValueError("AI returned invalid JSON") from None
        candidate = cleaned[start : last + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return json.loads(sanitize_json(candidate))
