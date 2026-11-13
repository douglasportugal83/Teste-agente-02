"""Desempenho: limites folgados que detectam regressões grosseiras (ex.: N+1, full scans)."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models import MarketCandle, Symbol
from app.models.enums import Timeframe

pytestmark = pytest.mark.performance


def test_overview_latency(client: TestClient, admin_headers: dict[str, str]) -> None:
    durations = []
    for _ in range(30):
        start = time.perf_counter()
        assert client.get("/api/v1/dashboard/overview", headers=admin_headers).status_code == 200
        durations.append(time.perf_counter() - start)
    durations.sort()
    p95 = durations[int(len(durations) * 0.95) - 1]
    assert p95 < 0.25, f"p95 do overview = {p95 * 1000:.1f} ms"


def test_bulk_candle_insert_and_range_query(db: Session) -> None:
    symbol = db.scalars(select(Symbol)).first()
    assert symbol is not None
    start_ts = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [
        {
            "symbol_id": symbol.id,
            "timeframe": Timeframe.M1,
            "ts": start_ts + timedelta(minutes=i),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        }
        for i in range(20_000)
    ]
    started = time.perf_counter()
    db.execute(insert(MarketCandle), rows)
    db.commit()
    insert_seconds = time.perf_counter() - started

    started = time.perf_counter()
    count = db.scalar(
        select(func.count())
        .select_from(MarketCandle)
        .where(
            MarketCandle.symbol_id == symbol.id,
            MarketCandle.timeframe == Timeframe.M1,
            MarketCandle.ts >= start_ts + timedelta(minutes=5_000),
            MarketCandle.ts < start_ts + timedelta(minutes=6_000),
        )
    )
    query_seconds = time.perf_counter() - started

    assert count == 1_000
    assert insert_seconds < 10, f"inserção de 20k candles levou {insert_seconds:.2f}s"
    assert query_seconds < 0.5, f"consulta por intervalo levou {query_seconds:.3f}s"
