"""Integração: restrições de integridade e de segurança impostas pelo banco."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DataSource, MarketCandle, SimulationAccount, Symbol, User
from app.models.enums import DataSourceKind, Timeframe
from tests.conftest import register


def _candle(symbol: Symbol, **overrides: float) -> MarketCandle:
    values = {"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0}
    values.update(overrides)
    return MarketCandle(
        symbol_id=symbol.id,
        timeframe=Timeframe.H1,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        **values,
    )


def test_candle_ohlc_consistency_is_enforced(db: Session) -> None:
    symbol = db.scalars(select(Symbol)).first()
    assert symbol is not None
    db.add(_candle(symbol))
    db.commit()

    for bad in ({"high": 8.0}, {"low": 11.5}, {"volume": -1.0}):
        db.add(_candle(symbol, **bad))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_duplicate_candle_is_rejected(db: Session) -> None:
    symbol = db.scalars(select(Symbol)).first()
    assert symbol is not None
    db.add(_candle(symbol))
    db.commit()
    db.expunge_all()
    db.add(_candle(symbol))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_data_source_cannot_be_writable(db: Session) -> None:
    db.add(DataSource(name="escrita", kind=DataSourceKind.MT5, read_only=False))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_simulation_account_cannot_be_real(client: TestClient, db: Session) -> None:
    register(client, "conta@example.com")
    user = db.scalar(select(User).where(User.email == "conta@example.com"))
    assert user is not None
    db.add(
        SimulationAccount(
            user_id=user.id,
            name="real",
            initial_balance=Decimal("1"),
            balance=Decimal("1"),
            equity=Decimal("1"),
            peak_equity=Decimal("1"),
            is_virtual=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
