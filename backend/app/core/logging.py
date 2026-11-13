"""Logs estruturados em JSON com redação de campos sensíveis."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = (
    "password",
    "senha",
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "cookie",
)
REDACTED = "***REDACTED***"

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact(value: Any) -> Any:
    """Substitui recursivamente valores cujas chaves indicam dado sensível."""
    if isinstance(value, dict):
        return {
            k: REDACTED if any(s in str(k).lower() for s in SENSITIVE_KEYS) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}
        payload.update(redact(extras))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # O log de acesso do uvicorn inclui query strings (ex.: token do WebSocket); usamos o nosso.
    logging.getLogger("uvicorn.access").disabled = True
