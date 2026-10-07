"""T15: PyJWT replaced python-jose. The token below was generated with python-jose
BEFORE the swap (fixtures/jose_hs256_token.json) and must still decode."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest

from app.core.config import settings
from app.core.security import ALGORITHM, TOKEN_TTL, decode_token, sign_token

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "jose_hs256_token.json").read_text(encoding="utf-8")
)


def test_token_made_by_python_jose_still_decodes_with_same_claims() -> None:
    payload = decode_token(FIXTURE["token"])
    assert payload is not None
    assert payload == FIXTURE["claims"]


def test_new_token_roundtrip_has_same_claims_shape_and_7_day_ttl() -> None:
    token = sign_token("64b7f0f0f0f0f0f0f0f0f0f1", 5, "admin")
    payload = decode_token(token)
    assert payload is not None
    assert set(payload) == {"userId", "tokenVersion", "role", "exp"}
    assert payload["userId"] == "64b7f0f0f0f0f0f0f0f0f0f1"
    assert payload["tokenVersion"] == 5 and payload["role"] == "admin"
    remaining = datetime.fromtimestamp(payload["exp"], UTC) - datetime.now(UTC)
    assert timedelta(days=7) - timedelta(minutes=1) < remaining <= TOKEN_TTL
    assert jwt.get_unverified_header(token)["alg"] == ALGORITHM == "HS256"


def test_new_tokens_are_readable_by_the_old_library_format() -> None:
    """Same wire format both ways, so a rollback to python-jose would not log
    everyone out: header/payload are plain base64url JSON with HS256."""
    token = sign_token("64b7f0f0f0f0f0f0f0f0f0f2", 1, "user")
    head, body, _sig = token.split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
    assert json.loads(base64.urlsafe_b64decode(pad(head)))["alg"] == "HS256"
    assert json.loads(base64.urlsafe_b64decode(pad(body)))["role"] == "user"


def _forge(payload: dict[str, Any], key: str, alg: str) -> str:
    return jwt.encode(payload, key, algorithm=alg)


def test_wrong_secret_expired_garbage_and_missing_exp_rejected() -> None:
    good: dict[str, Any] = {
        "userId": "x",
        "tokenVersion": 0,
        "role": "user",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    assert (
        decode_token(_forge(good, "some-other-secret-that-is-long-enough-0123456789", "HS256"))
        is None
    )
    expired = {**good, "exp": datetime.now(UTC) - timedelta(seconds=5)}
    assert decode_token(_forge(expired, settings.jwt_secret, "HS256")) is None
    no_exp = {k: v for k, v in good.items() if k != "exp"}
    assert decode_token(_forge(no_exp, settings.jwt_secret, "HS256")) is None
    for junk in ("", "abc", "a.b.c", "....", FIXTURE["token"][:-3] + "AAA"):
        assert decode_token(junk) is None


def test_alg_none_and_other_algorithms_are_refused() -> None:
    payload = {"userId": "x", "tokenVersion": 0, "role": "admin", "exp": 4102444800}
    unsigned = jwt.encode(payload, key=None, algorithm="none")  # type: ignore[arg-type]
    assert decode_token(unsigned) is None
    # HS512 with the right secret is not on the allow-list either
    assert decode_token(_forge(payload, settings.jwt_secret, "HS512")) is None

    # hand-built "none" token with a stripped signature
    def b64(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    handmade = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(payload)}."
    assert decode_token(handmade) is None


@pytest.mark.parametrize("tamper", ["role", "userId"])
def test_tampered_payload_rejected(tamper: str) -> None:
    head, body, sig = FIXTURE["token"].split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
    claims = json.loads(base64.urlsafe_b64decode(pad(body)))
    claims[tamper] = "admin" if tamper == "role" else "64b7f0f0f0f0f0f0f0f0f0ff"
    new_body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    assert decode_token(f"{head}.{new_body}.{sig}") is None


def test_python_jose_is_gone_from_requirements_and_source() -> None:
    root = Path(__file__).resolve().parents[2]
    assert "jose" not in (root / "requirements.txt").read_text(encoding="utf-8").lower()
    for path in (root / "app").rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        assert "from jose" not in path.read_text(encoding="utf-8"), path.name
