import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk
from app.models.enums import AlertSeverity, Timeframe
from app.models.market import str_enum


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_user_created", "user_id", "created_at"),)

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    severity: Mapped[AlertSeverity] = mapped_column(
        str_enum(AlertSeverity, "alert_severity"), default=AlertSeverity.INFO
    )
    category: Mapped[str] = mapped_column(String(40))  # system | risk | data | simulator
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    context: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[created_at]


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"
    __table_args__ = (Index("ix_ai_analysis_user_created", "user_id", "created_at"),)

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), index=True
    )
    timeframe: Mapped[Timeframe | None] = mapped_column(str_enum(Timeframe, "ai_timeframe"))
    analysis_type: Mapped[str] = mapped_column(String(40))  # regime | confluence | anomaly | ...
    summary: Mapped[str] = mapped_column(Text)
    # Dados que sustentam a conclusão (exigência de explicabilidade).
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    model: Mapped[str | None] = mapped_column(String(100))  # NULL = motor determinístico
    created_at: Mapped[created_at]


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[created_at]
