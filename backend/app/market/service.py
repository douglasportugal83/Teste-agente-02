"""Ingestão, sincronização e consulta de candles."""

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.market.candles import CandleBatch, FloatArray
from app.market.connectors.base import MarketDataConnector, SymbolInfo
from app.market.quality import ValidationResult, validate_batch
from app.market.timeframes import TIMEFRAME_SECONDS, from_epoch, to_epoch
from app.models import Alert, DataSource, MarketCandle, Role, Symbol, User
from app.models.enums import (
    AlertSeverity,
    AssetCategory,
    DataSourceKind,
    DataSourceStatus,
    Timeframe,
)
from app.services.catalog import ROLE_ADMIN

logger = logging.getLogger("traderai.market")

UPSERT_CHUNK = 2_000
_VALUE_COLUMNS = ("open", "high", "low", "close", "volume", "spread")

# Profundidade do histórico carregado na primeira sincronização de cada série.
DEFAULT_DEPTH: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(days=3),
    Timeframe.M5: timedelta(days=10),
    Timeframe.M15: timedelta(days=30),
    Timeframe.M30: timedelta(days=60),
    Timeframe.H1: timedelta(days=180),
    Timeframe.H4: timedelta(days=365),
    Timeframe.D1: timedelta(days=3 * 365),
    Timeframe.W1: timedelta(days=5 * 365),
}


def upsert_candles(
    db: Session, symbol_id: uuid.UUID, timeframe: Timeframe, batch: CandleBatch
) -> int:
    """Insere ou atualiza candles (idempotente). O chamador faz o commit."""
    if len(batch) == 0:
        return 0
    insert_fn: Any = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert_fn(MarketCandle)
    statement = statement.on_conflict_do_update(
        index_elements=["symbol_id", "timeframe", "ts"],
        set_={column: statement.excluded[column] for column in _VALUE_COLUMNS},
    )
    rows = batch.to_rows(symbol_id, timeframe)
    for start in range(0, len(rows), UPSERT_CHUNK):
        db.execute(statement, rows[start : start + UPSERT_CHUNK])
    return len(rows)


def ingest(
    db: Session, symbol: Symbol, timeframe: Timeframe, batch: CandleBatch, now: datetime
) -> ValidationResult:
    """Valida e grava. Linhas inválidas são rejeitadas e contabilizadas."""
    result = validate_batch(batch, timeframe, now=now)
    upsert_candles(db, symbol.id, timeframe, result.batch)
    if result.rows_rejected:
        logger.warning(
            "candles_rejected",
            extra={"symbol": symbol.name, "timeframe": timeframe.value, "reasons": result.rejected},
        )
    return result


def get_or_create_source(db: Session, name: str, kind: DataSourceKind) -> DataSource:
    source = db.scalar(select(DataSource).where(DataSource.name == name))
    if source is None:
        source = DataSource(name=name, kind=kind, status=DataSourceStatus.NOT_CONFIGURED)
        db.add(source)
        db.flush()
    return source


def sync_symbols(db: Session, source: DataSource, infos: Iterable[SymbolInfo]) -> tuple[int, int]:
    """Registra os símbolos descobertos na fonte. Devolve (novos, já existentes)."""
    existing = {
        s.name: s for s in db.scalars(select(Symbol).where(Symbol.data_source_id == source.id))
    }
    created = 0
    for info in infos:
        symbol = existing.get(info.name)
        if symbol is None:
            db.add(
                Symbol(
                    data_source_id=source.id,
                    name=info.name,
                    canonical_name=info.canonical_name,
                    description=info.description,
                    category=info.category,
                    base_currency=info.base_currency,
                    quote_currency=info.quote_currency,
                    digits=info.digits,
                    is_monitored=info.monitor_by_default,
                )
            )
            created += 1
        else:
            # A escolha do usuário sobre monitorar ou não é preservada.
            symbol.description = info.description or symbol.description
            symbol.digits = info.digits
    db.flush()
    return created, len(existing)


def mark_source_ok(db: Session, source: DataSource, now: datetime) -> None:
    source.status = DataSourceStatus.CONNECTED
    source.last_sync_at = now
    source.last_error = None
    if "note" in source.config:
        source.config = {k: v for k, v in source.config.items() if k != "note"}


def mark_source_error(db: Session, source: DataSource, message: str) -> None:
    """Marca a fonte com erro e avisa os administradores uma vez por transição."""
    was_error = source.status is DataSourceStatus.ERROR
    source.status = DataSourceStatus.ERROR
    source.last_error = message[:500]
    if not was_error:
        admins = db.scalars(select(User.id).join(Role).where(Role.name == ROLE_ADMIN))
        for admin_id in admins:
            db.add(
                Alert(
                    user_id=admin_id,
                    severity=AlertSeverity.CRITICAL,
                    category="data",
                    title=f"Fonte de dados com erro: {source.name}",
                    message=source.last_error,
                )
            )


def last_timestamps(db: Session, source_id: uuid.UUID) -> dict[tuple[uuid.UUID, Timeframe], int]:
    rows = db.execute(
        select(MarketCandle.symbol_id, MarketCandle.timeframe, func.max(MarketCandle.ts))
        .join(Symbol, Symbol.id == MarketCandle.symbol_id)
        .where(Symbol.data_source_id == source_id)
        .group_by(MarketCandle.symbol_id, MarketCandle.timeframe)
    ).all()
    return {(symbol_id, Timeframe(tf)): to_epoch(ts) for symbol_id, tf, ts in rows}


@dataclass
class SyncStats:
    series: int = 0
    candles: int = 0
    rejected: int = 0
    errors: list[str] = field(default_factory=list)


def sync_source(
    db: Session,
    connector: MarketDataConnector,
    source: DataSource,
    now: datetime,
    *,
    timeframes: Iterable[Timeframe] = tuple(Timeframe),
    depth: dict[Timeframe, timedelta] | None = None,
) -> SyncStats:
    """Sincronização incremental dos símbolos monitorados: busca só o que falta desde o
    último candle gravado (ou o histórico inicial, se a série estiver vazia)."""
    depth = depth or DEFAULT_DEPTH
    stats = SyncStats()
    last = last_timestamps(db, source.id)
    now_ts = to_epoch(now)
    symbols = db.scalars(
        select(Symbol)
        .where(Symbol.data_source_id == source.id, Symbol.is_monitored)
        .order_by(Symbol.name)
    ).all()
    for symbol in symbols:
        for timeframe in timeframes:
            size = TIMEFRAME_SECONDS[timeframe]
            previous = last.get((symbol.id, timeframe))
            if previous is not None and previous + 2 * size > now_ts:
                continue  # ainda não há candle novo fechado
            start = from_epoch(previous + size) if previous is not None else now - depth[timeframe]
            try:
                batch = connector.fetch_candles(symbol.name, timeframe, start, now)
            except Exception as exc:  # noqa: BLE001 — uma série com falha não derruba as demais
                stats.errors.append(f"{symbol.name} {timeframe.value}: {exc}")
                continue
            result = ingest(db, symbol, timeframe, batch, now)
            stats.series += 1
            stats.candles += len(result.batch)
            stats.rejected += result.rows_rejected
        db.commit()

    if stats.errors and stats.candles == 0 and stats.series == 0:
        mark_source_error(db, source, "; ".join(stats.errors[:3]))
    else:
        mark_source_ok(db, source, now)
        if stats.errors:
            source.last_error = "; ".join(stats.errors[:3])[:500]
    db.commit()
    return stats


def backfill(
    db: Session,
    connector: MarketDataConnector,
    symbols: Iterable[Symbol],
    timeframes: Iterable[Timeframe],
    start: datetime,
    end: datetime,
    now: datetime,
) -> SyncStats:
    """Carrega (ou recarrega) um intervalo histórico explícito."""
    stats = SyncStats()
    timeframes = list(timeframes)
    for symbol in symbols:
        for timeframe in timeframes:
            batch = connector.fetch_candles(symbol.name, timeframe, start, min(end, now))
            result = ingest(db, symbol, timeframe, batch, now)
            stats.series += 1
            stats.candles += len(result.batch)
            stats.rejected += result.rows_rejected
        db.commit()
    return stats


def load_candles(
    db: Session,
    symbol_id: uuid.UUID,
    timeframe: Timeframe,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int | None = None,
) -> CandleBatch:
    """Candles em ordem cronológica; com `limit`, os mais recentes do intervalo."""
    query = select(
        MarketCandle.ts,
        MarketCandle.open,
        MarketCandle.high,
        MarketCandle.low,
        MarketCandle.close,
        MarketCandle.volume,
        MarketCandle.spread,
    ).where(MarketCandle.symbol_id == symbol_id, MarketCandle.timeframe == timeframe)
    if start is not None:
        query = query.where(MarketCandle.ts >= start)
    if end is not None:
        query = query.where(MarketCandle.ts < end)
    query = query.order_by(MarketCandle.ts.desc())
    if limit is not None:
        query = query.limit(limit)
    rows = db.execute(query).all()[::-1]
    if not rows:
        return CandleBatch.empty()
    columns = list(zip(*rows, strict=True))

    def as_float(values: tuple[float | None, ...]) -> FloatArray:
        return np.array([np.nan if v is None else v for v in values], dtype=np.float64)

    return CandleBatch(
        np.array([to_epoch(t) for t in columns[0]], dtype=np.int64),
        *(as_float(columns[i]) for i in range(1, 7)),
    )


@dataclass
class Coverage:
    symbol_id: uuid.UUID
    timeframe: Timeframe
    candles: int
    first_ts: datetime
    last_ts: datetime


def coverage(db: Session, source_id: uuid.UUID | None = None) -> list[Coverage]:
    query = select(
        MarketCandle.symbol_id,
        MarketCandle.timeframe,
        func.count(),
        func.min(MarketCandle.ts),
        func.max(MarketCandle.ts),
    ).group_by(MarketCandle.symbol_id, MarketCandle.timeframe)
    if source_id is not None:
        query = query.join(Symbol, Symbol.id == MarketCandle.symbol_id).where(
            Symbol.data_source_id == source_id
        )
    return [
        Coverage(symbol_id, Timeframe(tf), count, from_epoch(to_epoch(a)), from_epoch(to_epoch(b)))
        for symbol_id, tf, count, a, b in db.execute(query)
    ]


@dataclass
class Quote:
    symbol_id: uuid.UUID
    name: str
    canonical_name: str
    category: AssetCategory
    digits: int
    source_kind: DataSourceKind
    price: float | None
    price_ts: datetime | None
    change_pct: float | None  # contra o fechamento do último dia completo
    is_stale: bool


def staleness_tolerance(timeframe: Timeframe, always_open: bool) -> int:
    """Atraso tolerado (s) do último candle fechado; folga de fim de semana se não for 24/7."""
    return 3 * TIMEFRAME_SECONDS[timeframe] + (0 if always_open else 3 * 86_400)


def quotes(db: Session, now: datetime) -> list[Quote]:
    """Último preço de cada símbolo monitorado (menor timeframe disponível)."""
    rows = db.execute(
        select(Symbol, DataSource.kind)
        .join(DataSource)
        .where(Symbol.is_monitored, DataSource.is_enabled)
        .order_by(Symbol.category, Symbol.canonical_name)
    ).all()
    result = []
    for symbol, kind in rows:
        latest = None
        for timeframe in Timeframe:
            latest = db.execute(
                select(MarketCandle.ts, MarketCandle.close)
                .where(MarketCandle.symbol_id == symbol.id, MarketCandle.timeframe == timeframe)
                .order_by(MarketCandle.ts.desc())
                .limit(1)
            ).first()
            if latest is not None:
                break
        price = price_ts = change = None
        stale = True
        if latest is not None:
            price_ts, price = from_epoch(to_epoch(latest[0])), float(latest[1])
            always_open = symbol.category is AssetCategory.CRYPTO
            age = to_epoch(now) - to_epoch(price_ts) - TIMEFRAME_SECONDS[timeframe]
            stale = age > staleness_tolerance(timeframe, always_open)
            day_close = db.scalar(
                select(MarketCandle.close)
                .where(
                    MarketCandle.symbol_id == symbol.id,
                    MarketCandle.timeframe == Timeframe.D1,
                    MarketCandle.ts < price_ts.replace(hour=0, minute=0, second=0, microsecond=0),
                )
                .order_by(MarketCandle.ts.desc())
                .limit(1)
            )
            if day_close:
                change = (price / float(day_close) - 1.0) * 100.0
        result.append(
            Quote(
                symbol_id=symbol.id,
                name=symbol.name,
                canonical_name=symbol.canonical_name,
                category=symbol.category,
                digits=symbol.digits,
                source_kind=kind,
                price=price,
                price_ts=price_ts,
                change_pct=change,
                is_stale=stale,
            )
        )
    return result
