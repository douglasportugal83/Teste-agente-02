import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk
from app.models.enums import AssetCategory, DataSourceKind, DataSourceStatus, Timeframe


def str_enum(enum_cls: type, name: str) -> Enum:
    """Enum armazenado como VARCHAR + CHECK (portável e simples de migrar)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=40,
        values_callable=lambda e: [m.value for m in e],
    )


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"
    __table_args__ = (
        # Fontes de dados são exclusivamente de leitura: garantido também no banco.
        CheckConstraint("read_only", name="read_only_enforced"),
    )

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[DataSourceKind] = mapped_column(str_enum(DataSourceKind, "data_source_kind"))
    status: Mapped[DataSourceStatus] = mapped_column(
        str_enum(DataSourceStatus, "data_source_status"),
        default=DataSourceStatus.NOT_CONFIGURED,
    )
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Configuração não sensível. Credenciais ficam em variáveis de ambiente, nunca aqui.
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    symbols: Mapped[list["Symbol"]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )


class Symbol(Base, TimestampMixin):
    __tablename__ = "symbols"
    __table_args__ = (UniqueConstraint("data_source_id", "name"),)

    id: Mapped[uuid_pk]
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(40), index=True)  # símbolo na fonte (ex.: USTEC)
    canonical_name: Mapped[str] = mapped_column(String(40), index=True)  # ex.: NAS100
    description: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[AssetCategory] = mapped_column(
        str_enum(AssetCategory, "asset_category"), index=True
    )
    base_currency: Mapped[str | None] = mapped_column(String(10))
    quote_currency: Mapped[str | None] = mapped_column(String(10))
    digits: Mapped[int] = mapped_column(Integer, default=2)
    contract_size: Mapped[Decimal] = mapped_column(default=Decimal("1"))
    trading_hours: Mapped[dict[str, Any] | None] = mapped_column()
    is_monitored: Mapped[bool] = mapped_column(Boolean, default=True)

    data_source: Mapped[DataSource] = relationship(back_populates="symbols")


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        CheckConstraint("high >= low", name="high_gte_low"),
        CheckConstraint("high >= open AND high >= close", name="high_is_max"),
        CheckConstraint("low <= open AND low <= close", name="low_is_min"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
    )

    # A PK composta já é o índice de consulta (símbolo, timeframe, tempo) e impede duplicatas.
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), primary_key=True
    )
    timeframe: Mapped[Timeframe] = mapped_column(str_enum(Timeframe, "timeframe"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)  # abertura, UTC
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    spread: Mapped[float | None] = mapped_column(Float)
