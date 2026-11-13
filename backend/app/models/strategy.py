import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, created_at, uuid_pk
from app.models.enums import StrategyFamily
from app.models.market import str_enum


class Strategy(Base, TimestampMixin):
    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("owner_id", "key"),
        # Estratégias nativas (owner_id NULL) também precisam de chave única.
        Index(
            "uq_strategies_builtin_key",
            "key",
            unique=True,
            postgresql_where=text("owner_id IS NULL"),
            sqlite_where=text("owner_id IS NULL"),
        ),
    )

    id: Mapped[uuid_pk]
    # NULL = estratégia nativa do sistema, visível a todos os usuários.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    family: Mapped[StrategyFamily] = mapped_column(str_enum(StrategyFamily, "strategy_family"))
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    versions: Mapped[list["StrategyVersion"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan", order_by="StrategyVersion.version"
    )


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)

    id: Mapped[uuid_pk]
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict)
    changelog: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[created_at]

    strategy: Mapped[Strategy] = relationship(back_populates="versions")
    parameters: Mapped[list["StrategyParameter"]] = relationship(
        back_populates="strategy_version", cascade="all, delete-orphan"
    )


class StrategyParameter(Base):
    __tablename__ = "strategy_parameters"
    __table_args__ = (UniqueConstraint("strategy_version_id", "name"),)

    id: Mapped[uuid_pk]
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    value_type: Mapped[str] = mapped_column(String(20))  # int | float | bool | str | json
    value: Mapped[dict[str, Any]] = mapped_column()  # {"v": <valor>}
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)

    strategy_version: Mapped[StrategyVersion] = relationship(back_populates="parameters")
