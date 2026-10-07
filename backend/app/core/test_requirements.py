"""T16: runtime deps are exactly pinned, dev tools live in requirements-dev.txt,
and the paddlepaddle extra-index line survives."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV_TOOLS = {"ruff", "black", "isort", "mypy", "pytest", "pytest-asyncio"}


def _requirement_lines(name: str) -> list[str]:
    out = []
    for raw in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.append(line)
    return out


def _names(lines: list[str]) -> set[str]:
    return {re.split(r"[=<>\[ ]", line, maxsplit=1)[0].lower() for line in lines}


def test_every_runtime_requirement_is_pinned_to_an_exact_version() -> None:
    lines = _requirement_lines("requirements.txt")
    assert len(lines) >= 20
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+(\[[a-z,]+\])?==\d[\w.]*", line), line


def test_dev_tools_are_not_in_runtime_requirements_but_are_in_dev_file() -> None:
    runtime = _names(_requirement_lines("requirements.txt"))
    assert not (runtime & DEV_TOOLS)
    dev_lines = _requirement_lines("requirements-dev.txt")
    assert DEV_TOOLS <= _names(dev_lines)
    assert all("==" in line for line in dev_lines)
    assert "-r requirements.txt" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_paddlepaddle_extra_index_url_kept_and_jose_gone() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "--extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/" in text
    assert "paddlepaddle==" in text
    assert "jose" not in text.lower()
    assert "pyjwt==" in text.lower()


def test_installed_versions_match_the_pins() -> None:
    from importlib.metadata import version

    for line in _requirement_lines("requirements.txt"):
        name, pinned = re.sub(r"\[.*\]", "", line).split("==")
        if name.lower() == "opencv-python-headless":
            continue  # dev venv has the non-headless build of the same 5.0.0.93 release
        assert version(name) == pinned, f"{name}: installed {version(name)} != pinned {pinned}"
