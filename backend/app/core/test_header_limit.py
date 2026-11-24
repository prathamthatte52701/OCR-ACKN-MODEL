"""The server must refuse absurdly large request headers. uvicorn's default parser here is
httptools, which has no header-size option (a 3 MB header got 200 OK), so the start command selects
the h11 parser with --h11-max-incomplete-event-size 32768 (32 KB: a real request is under 3 KB, even
with a JWT, cookies and browser headers).

These tests read the flags from the REAL start commands (start.bat and the README developer
command), so the documented command and the tested behavior cannot drift apart, and run a real
uvicorn with exactly those flags in front of a tiny app (no database needed)."""

import re
import shlex
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WANT = "--http h11 --h11-max-incomplete-event-size 32768"
TINY_APP = """
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            else:
                await send({"type": "lifespan.shutdown.complete"})
                return
    head = {"type": "http.response.start", "status": 200, "headers": [(b"x-t", b"1")]}
    await send(head)
    await send({"type": "http.response.body", "body": b"ok"})
"""


def _start_bat_flags() -> list[str]:
    text = (ROOT / "start.bat").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"-m uvicorn app\.main:app ([^\r\n\"]*)", text)
    assert m, "uvicorn start command not found in start.bat"
    return shlex.split(m.group(1))


def test_start_bat_and_readme_use_the_header_limit() -> None:
    assert WANT in " ".join(_start_bat_flags())
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    line = next(ln for ln in readme.splitlines() if "-m uvicorn app.main:app" in ln)
    assert WANT in line, line


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _request(port: int, headers: bytes) -> str:
    s = socket.create_connection(("127.0.0.1", port), timeout=15)
    try:
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n" + headers + b"\r\n")
        data = b""
        while b"\r\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.split(b"\r\n")[0].decode(errors="replace")
    finally:
        s.close()


@pytest.fixture
def server(tmp_path: Path) -> Iterator[int]:
    (tmp_path / "tiny.py").write_text(TINY_APP, encoding="utf-8")
    port = _free_port()
    flags = [f for f in _start_bat_flags()]
    # same flags as start.bat, only the host/port are ours
    for i, f in enumerate(flags):
        if f == "--port":
            flags[i + 1] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tiny:app", *flags],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                if _request(port, b"").startswith("HTTP/1.1 200"):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("test server did not start")
        yield port
    finally:
        proc.kill()
        proc.wait(timeout=20)


@pytest.mark.parametrize(
    "headers",
    [
        b"Authorization: Bearer " + b"a" * 300 + b"\r\nCookie: " + b"c" * 800 + b"\r\n",
        b"X-Big: " + b"a" * 8000 + b"\r\n",
        b"X-Big: " + b"a" * 20000 + b"\r\n",
        b"".join(b"X-%d: " % i + b"b" * 20 + b"\r\n" for i in range(600)),  # many headers, 20 KB
    ],
    ids=["jwt+cookie", "8KB", "20KB", "600 headers"],
)
def test_normal_and_fairly_large_headers_still_work(server: int, headers: bytes) -> None:
    assert _request(server, headers).startswith("HTTP/1.1 200")


@pytest.mark.parametrize(
    "headers",
    [
        b"X-Big: " + b"a" * 100_000 + b"\r\n",
        b"X-Big: " + b"a" * 1_000_000 + b"\r\n",
        b"X-Big: " + b"a" * 3_000_000 + b"\r\n",
        b"".join(b"X-%d: " % i + b"b" * 40 + b"\r\n" for i in range(2000)),  # many headers, 100 KB
    ],
    ids=["100KB", "1MB", "3MB", "2000 headers"],
)
def test_huge_headers_get_a_clean_rejection_and_the_server_stays_healthy(
    server: int, headers: bytes
) -> None:
    started = time.monotonic()
    status = _request(server, headers)
    assert status.split()[1] in ("400", "431"), status  # a clean refusal, not 200 / 500 / a hang
    assert time.monotonic() - started < 10
    assert _request(server, b"").startswith("HTTP/1.1 200")  # and it keeps serving
