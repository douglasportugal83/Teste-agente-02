"""Trilha de auditoria: grava em audit_logs e no log estruturado, com redação de segredos."""

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.models import AuditLog

logger = logging.getLogger("traderai.audit")


def record(
    db: Session,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Adiciona o registro à sessão; o commit é responsabilidade do chamador."""
    safe_details = redact(details or {})
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=safe_details,
        ip_address=ip_address,
    )
    db.add(entry)
    logger.info(
        "audit",
        extra={
            "action": action,
            "user_id": str(user_id) if user_id else None,
            "entity_type": entity_type,
            "entity_id": entry.entity_id,
            "details": safe_details,
        },
    )
    return entry
