"""Duração e alinhamento dos timeframes. Todos os horários internos são UTC."""

from datetime import UTC, datetime

from app.models.enums import Timeframe

TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14_400,
    Timeframe.D1: 86_400,
    Timeframe.W1: 604_800,
}

# 1970-01-01 foi uma quinta-feira; semanas (W1) começam na segunda 1970-01-05 00:00 UTC.
_WEEK_ORIGIN = 4 * 86_400


def bucket_origin(timeframe: Timeframe) -> int:
    return _WEEK_ORIGIN if timeframe is Timeframe.W1 else 0


def floor_ts(ts: int, timeframe: Timeframe) -> int:
    """Início (epoch, s) do candle que contém `ts`."""
    size, origin = TIMEFRAME_SECONDS[timeframe], bucket_origin(timeframe)
    return (ts - origin) // size * size + origin


def is_aligned(ts: int, timeframe: Timeframe) -> bool:
    return floor_ts(ts, timeframe) == ts


def to_epoch(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp())


def from_epoch(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)
