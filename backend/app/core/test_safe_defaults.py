"""T14: docs off by default, no admin identities in source, localhost default."""

import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def _routes_with_env(enable_docs: str | None) -> list[str]:
    """Imports a fresh app in a subprocess with the given ENABLE_DOCS and returns
    the doc-related paths FastAPI registered."""
    code = (
        "import json; from app.main import app; "
        "print(json.dumps(sorted(p for p in (getattr(r, 'path', None) for r in app.routes) "
        "if p in ('/docs', '/redoc', '/openapi.json'))))"
    )
    env = {
        **__import__("os").environ,
        "MONGO_DB_NAME": "ackn_AI_model_test",
        "PYTHONPATH": str(BACKEND),
    }
    env.pop("ENABLE_DOCS", None)
    if enable_docs is not None:
        env["ENABLE_DOCS"] = enable_docs
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("value", [None, "false", "", "0"])
def test_docs_off_by_default_and_when_false(value: str | None) -> None:
    assert _routes_with_env(value) == []


def test_docs_on_only_when_explicitly_enabled() -> None:
    assert _routes_with_env("true") == ["/docs", "/openapi.json", "/redoc"]


async def test_docs_paths_404_in_running_app(client: object) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(path)).status_code == 404  # type: ignore[attr-defined]


def test_no_real_admin_identity_hardcoded_in_source() -> None:
    offenders = []
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"arjav99jain|prathamthatte527|Arjav Jain|Pratham Thatte", text):
            offenders.append(path.name)
    assert offenders == []


def test_seed_admin_reads_identities_from_settings() -> None:
    seed = importlib.import_module("app.scripts.seed_admin")
    assert {a["vars"] for a in seed.ADMINS} == {
        "ADMIN_1_NAME / ADMIN_1_EMAIL / ADMIN_1_PASSWORD",
        "ADMIN_2_NAME / ADMIN_2_EMAIL / ADMIN_2_PASSWORD",
    }


def test_app_never_starts_a_server_bound_to_all_interfaces() -> None:
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "0.0.0.0" not in text, path.name
        assert "uvicorn.run" not in text, path.name  # CLI default host is 127.0.0.1
