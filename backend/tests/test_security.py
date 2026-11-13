import json
import logging
import uuid

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import REDACTED, JsonFormatter, redact
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.rate_limit import FailureLimiter


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("Senha-forte-123")
    assert hashed != "Senha-forte-123"
    assert verify_password("Senha-forte-123", hashed)
    assert not verify_password("outra-senha", hashed)
    assert not verify_password("x", "hash-invalido")


def test_long_passwords_are_not_truncated() -> None:
    base = "a" * 80
    assert not verify_password(base + "X", hash_password(base + "Y"))


def test_token_roundtrip_and_rejections() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id)) == user_id
    assert decode_access_token(create_access_token(user_id, expires_minutes=-1)) is None
    assert decode_access_token("lixo") is None
    tampered = create_access_token(user_id)[:-2] + "xx"
    assert decode_access_token(tampered) is None


def test_redact_nested_secrets() -> None:
    data = {"email": "a@b.c", "password": "x", "nested": [{"Access_Token": "y", "ok": 1}]}
    assert redact(data) == {
        "email": "a@b.c",
        "password": REDACTED,
        "nested": [{"Access_Token": REDACTED, "ok": 1}],
    }


def test_json_log_formatter_redacts_extras() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "evento", (), None)
    record.jwt_secret = "super-secreto"
    record.user = "u1"
    line = JsonFormatter().format(record)
    assert "super-secreto" not in line
    assert json.loads(line)["user"] == "u1"


def test_trading_mode_only_accepts_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().trading_mode == "simulation"
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(ValidationError):
        Settings()


def test_production_requires_strong_secret() -> None:
    with pytest.raises(RuntimeError):
        Settings(environment="production", jwt_secret="change-me").validate_for_runtime()
    Settings(environment="production", jwt_secret="x" * 40).validate_for_runtime()


def test_database_url_normalization() -> None:
    assert Settings(database_url="postgres://u:p@h/db").database_url.startswith(
        "postgresql+psycopg://"
    )


def test_failure_limiter() -> None:
    limiter = FailureLimiter(max_failures=2, window_seconds=60)
    assert not limiter.is_blocked("k")
    limiter.register_failure("k")
    limiter.register_failure("k")
    assert limiter.is_blocked("k")
    assert not limiter.is_blocked("other")
    limiter.reset("k")
    assert not limiter.is_blocked("k")
