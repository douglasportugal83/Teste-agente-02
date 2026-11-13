import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at, uuid_pk
from app.models.enums import RunStatus, Timeframe
from app.models.market import str_enum


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint("period_end > period_start", name="period_valid"),
        CheckConstraint("initial_capital > 0", name="capital_positive"),
        Index("ix_backtest_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "run_status"), default=RunStatus.PENDING, index=True
    )
    symbols: Mapped[list[Any]] = mapped_column(default=list)
    timeframe: Mapped[Timeframe] = mapped_column(str_enum(Timeframe, "bt_timeframe"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_capital: Mapped[Decimal] = mapped_column()
    # spread, slippage, comissão, latência, divisão treino/validação, walk-forward etc.
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[created_at]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    result: Mapped["BacktestResult | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[uuid_pk]
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), unique=True
    )
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    net_return_pct: Mapped[float | None] = mapped_column(Float)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    expectancy: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    total_costs: Mapped[Decimal | None] = mapped_column()
    max_consecutive_wins: Mapped[int | None] = mapped_column(Integer)
    max_consecutive_losses: Mapped[int | None] = mapped_column(Integer)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float)
    equity_curve: Mapped[list[Any]] = mapped_column(default=list)
    trades: Mapped[list[Any]] = mapped_column(default=list)
    extra_metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[created_at]

    run: Mapped[BacktestRun] = relationship(back_populates="result")
