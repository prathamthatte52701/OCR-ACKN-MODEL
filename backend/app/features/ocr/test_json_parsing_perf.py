"""strip_markdown / sanitize_json / parse_extraction_json: linear time, and identical output to the
original regex implementation (kept below as the oracle)."""

import json
import random
import re
import time
from typing import Any

import pytest

from app.features.ocr import json_parsing as jp

# ---- the ORIGINAL implementation, verbatim, as the oracle ----
_START = re.compile(r"^```json\s*", re.IGNORECASE)
_START_PLAIN = re.compile(r"^```\s*")
_END = re.compile(r"\s*```$")
_CTRL = re.compile(r'"((?:[^"\\]|\\.)*)"')
_OBJ = re.compile(r"\{[\s\S]*\}")
_ESC = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def old_strip(text: str) -> str:
    text = _START.sub("", text)
    text = _START_PLAIN.sub("", text)
    text = _END.sub("", text)
    return text.strip()


def old_sanitize(text: str) -> str:
    def clean(m: re.Match) -> str:
        return re.sub(r"[\x00-\x1f\x7f]", lambda c: _ESC.get(c.group(0), ""), m.group(0))

    return _CTRL.sub(clean, text)


def old_parse(raw: str) -> Any:
    cleaned = old_sanitize(old_strip(raw))
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _OBJ.search(cleaned)
        if not match:
            raise ValueError("AI returned invalid JSON") from None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return json.loads(old_sanitize(match.group(0)))


def _timed(fn: Any, arg: str) -> float:
    start = time.perf_counter()
    try:
        fn(arg)
    except Exception:  # noqa: BLE001 - only the time matters here
        pass
    return time.perf_counter() - start


# ---------------- speed ----------------
N = 80_000


@pytest.mark.parametrize(
    "text",
    [
        " " * N,
        "\t" * N,
        "\n" * N,
        "\r\n" * (N // 2),
        "x" + " " * N + "y",
        "```json" + " " * N,
        "```json\n{}\n" + " " * N,
        "{}" + " \n" * (N // 2) + "```",
        "```" + " " * N + "```",
    ],
    ids=[
        "spaces",
        "tabs",
        "newlines",
        "crlf",
        "x-spaces-y",
        "fence-spaces",
        "json-trailing",
        "trail-fence",
        "fence-fence",
    ],
)
def test_strip_markdown_is_fast(text: str) -> None:
    assert _timed(jp.strip_markdown, text) < 0.1


@pytest.mark.parametrize(
    "text",
    ['"' + '\\"' * 20_000, '"' + "\\" * 40_000, '"a' * 20_000],
    ids=["escaped-quotes", "backslashes", "open-quotes"],
)
def test_sanitize_json_is_fast(text: str) -> None:
    assert _timed(jp.sanitize_json, text) < 0.5


@pytest.mark.parametrize(
    "text",
    [
        "{" * 40_000,
        "a{" * 20_000,
        '{"' * 20_000,
        "{" * 20_000 + "x",
        "}" * 40_000,
        '{"a": "' + '\\"' * 20_000 + "}",  # reaches the sanitize step through the parse path
        "{" + '"' * 40_000 + "}",
    ],
    ids=[
        "braces",
        "a-braces",
        "brace-quotes",
        "braces-x",
        "closers",
        "escaped-quotes-in-object",
        "quotes-in-object",
    ],
)
def test_parse_extraction_json_is_fast(text: str) -> None:
    assert _timed(jp.parse_extraction_json, text) < 0.5


# ---------------- same behaviour ----------------
CASES = [
    "",
    " ",
    "{}",
    '{"a": 1}',
    '```json\n{"number": "820762791", "date": "01/02/2026"}\n```',
    '```json {"a":1} ```',
    '```\n{"a":1}\n```',
    '```\n{"a":1}\n```\n',
    '```\n{"a":1}\n```\n\n',
    '```\n{"a":1}\n``` ',
    '{"a":1}```',
    '{"a":1}   ```   ',
    'text ``` middle ``` more {"a":1}',
    'Here you go:\n```json\n{"a": "x"}\n```\nThanks',
    '```JSON\n{"a":1}\n```',
    "``````",
    "```",
    "`` `",
    '{"a": "line1\nline2\ttab"}',
    '{"a": "bad \x01 control"}',
    'prefix {"a": 1} suffix',
    "no braces here",
    '{"a": 1',
    '"unterminated \\',
    '"\\\n"',
    '"a\\"b" "c"',
    '{"a": "\\\\"}',
    "\n\n```json\n{}\n```\n\n",
]


def _same(raw: str) -> None:
    assert jp.strip_markdown(raw) == old_strip(raw), repr(raw)
    assert jp.sanitize_json(raw) == old_sanitize(raw), repr(raw)
    try:
        want: Any = old_parse(raw)
    except Exception as exc:  # noqa: BLE001
        with pytest.raises(type(exc)):
            jp.parse_extraction_json(raw)
    else:
        assert jp.parse_extraction_json(raw) == want, repr(raw)


@pytest.mark.parametrize("raw", CASES, ids=[repr(c)[:30] for c in CASES])
def test_same_output_as_original(raw: str) -> None:
    _same(raw)


def test_known_outputs() -> None:
    assert jp.strip_markdown('```json\n{"a":1}\n```') == '{"a":1}'
    assert jp.strip_markdown('```\n{"a":1}\n```') == '{"a":1}'
    assert jp.strip_markdown('{"a":1}') == '{"a":1}'
    assert jp.strip_markdown('{"a":1}  ```  ') == '{"a":1}  ```'  # fence not at the very end
    assert jp.strip_markdown("") == ""
    assert jp.parse_extraction_json('```json\n{"number": "820762791"}\n```') == {
        "number": "820762791"
    }
    assert jp.parse_extraction_json('noise {"a": 1} noise') == {"a": 1}
    with pytest.raises(ValueError):
        jp.parse_extraction_json("no json at all")


def test_fuzz_same_output_as_original() -> None:
    rnd = random.Random(1234)
    alphabet = [
        " ",
        " ",
        "\n",
        "\t",
        "\r",
        "`",
        "`",
        "`",
        "{",
        "}",
        '"',
        "\\",
        "a",
        "1",
        ":",
        ",",
        "json",
        "```",
        "```json",
        "\x01",
        "\\\n",
        "\r\n",
        "\x7f",
        '\\"',
        '"a"',
    ]
    for _ in range(6000):
        raw = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 24)))
        _same(raw)
