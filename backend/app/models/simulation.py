"""Contas, ordens e posições ESTRITAMENTE virtuais (paper trading)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, created_at, uuid_pk
from app.models.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionStatus,
    RiskRuleType,
    SimulationStatus,
)
from app.models.market import str_enum


class SimulationAccount(Base, TimestampMixin):
    __tablename__ = "simulation_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        CheckConstraint("initial_balance > 0", name="initial_balance_positive"),
        # Não existe conta real neste sistema; a coluna documenta e trava essa garantia.
        CheckConstraint("is_virtual", name="virtual_only"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    initial_balance: Mapped[Decimal] = mapped_column()
    balance: Mapped[Decimal] = mapped_column()
    equity: Mapped[Decimal] = mapped_column()
    peak_equity: Mapped[Decimal] = mapped_column()
    status: Mapped[SimulationStatus] = mapped_column(
        str_enum(SimulationStatus, "simulation_status"), default=SimulationStatus.PAUSED
    )
    status_reason: Mapped[str | None] = mapped_column(Text)
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=True)

    orders: Mapped[list["SimulatedOrder"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    positions: Mapped[list["SimulatedPosition"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class SimulatedOrder(Base):
    __tablename__ = "simulated_orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_simulated_orders_account_created", "account_id", "created_at"),
    )

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulation_accounts.id", ondelete="CASCADE")
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("symbols.id", ondelete="RESTRICT"), index=True
    )
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="SET NULL")
    )
    side: Mapped[OrderSide] = mapped_column(str_enum(OrderSide, "order_side"))
    order_type: Mapped[OrderType] = mapped_column(str_enum(OrderType, "order_type"))
    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus, "order_status"), default=OrderStatus.PENDING
    )
    quantity: Mapped[float] = mapped_column(Float)
    requested_price: Mapped[float | None] = mapped_column(Float)
    filled_price: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    simulated_costs: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    reason: Mapped[str | None] = mapped_column(Text)  # motivo auditável da decisão
    created_at: Mapped[created_at]
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[SimulationAccount] = relationship(back_populates="orders")


class SimulatedPosition(Base):
    __tablename__ = "simulated_positions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_simulated_positions_account_status", "account_id", "status"),
    )

    id: Mapped[uuid_pk]
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulation_accounts.id", ondelete="CASCADE")
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("symbols.id", ondelete="RESTRICT"), index=True
    )
    entry_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("simulated_orders.id", ondelete="SET NULL")
    )
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="SET NULL")
    )
    side: Mapped[OrderSide] = mapped_column(str_enum(OrderSide, "position_side"))
    status: Mapped[PositionStatus] = mapped_column(
        str_enum(PositionStatus, "position_status"), default=PositionStatus.OPEN
    )
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[Decimal | None] = mapped_column()
    simulated_costs: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    open_reason: Mapped[str | None] = mapped_column(Text)
    close_reason: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[created_at]
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[SimulationAccount] = relationship(back_populates="positions")


class RiskRule(Base, TimestampMixin):
    __tablename__ = "risk_rules"
    __table_args__ = (
        UniqueConstraint("account_id", "rule_type"),
        CheckConstraint("value >= 0", name="value_non_negative"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulation_accounts.id", ondelete="CASCADE"), index=True
    )
    rule_type: Mapped[RiskRuleType] = mapped_column(str_enum(RiskRuleType, "risk_rule_type"))
    value: Mapped[float] = mapped_column(Float)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
