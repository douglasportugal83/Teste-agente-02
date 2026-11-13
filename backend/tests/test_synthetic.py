"""Gerador sintético: determinismo, coerência entre timeframes e ausência de look-ahead."""

import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.market.candles import CandleBatch
from app.market.connectors.base import ConnectorError
from app.market.connectors.synthetic import PROFILES, SyntheticConnector, aggregate
from app.market.quality import validate_batch
from app.market.timeframes import TIMEFRAME_SECONDS, floor_ts, is_aligned, to_epoch
from app.models.enums import Timeframe

NOW = datetime(2026, 11, 13, 12, 7, 30, tzinfo=UTC)  # sexta-feira


@pytest.fixture
def connector() -> SyntheticConnector:
    return SyntheticConnector(now=lambda: NOW)


def assert_same(a: CandleBatch, b: CandleBatch) -> None:
    for column in ("ts", "open", "high", "low", "close", "volume", "spread"):
        np.testing.assert_array_equal(getattr(a, column), getattr(b, column), err_msg=column)


def test_discovers_the_default_catalog(connector: SyntheticConnector) -> None:
    infos = connector.discover_symbols()
    assert {i.name for i in infos} == set(PROFILES)
    assert all(i.monitor_by_default for i in infos)


def test_same_request_is_deterministic(connector: SyntheticConnector) -> None:
    start = NOW - timedelta(days=5)
    first = connector.fetch_candles("XAUUSD", Timeframe.M5, start, NOW)
    again = SyntheticConnector(now=lambda: NOW).fetch_candles("XAUUSD", Timeframe.M5, start, NOW)
    assert len(first) > 1000
    assert_same(first, again)


def test_overlapping_windows_agree(connector: SyntheticConnector) -> None:
    """Pedir um trecho isolado devolve exatamente o mesmo que recortá-lo de um pedido maior."""
    wide = connector.fetch_candles("BTCUSD", Timeframe.H1, NOW - timedelta(days=200), NOW)
    start, end = NOW - timedelta(days=90), NOW - timedelta(days=30)
    narrow = connector.fetch_candles("BTCUSD", Timeframe.H1, start, end)
    assert_same(narrow, wide.select((wide.ts >= to_epoch(start)) & (wide.ts < to_epoch(end))))


@pytest.mark.parametrize("symbol", sorted(PROFILES))
def test_candles_pass_validation(connector: SyntheticConnector, symbol: str) -> None:
    batch = connector.fetch_candles(symbol, Timeframe.M15, NOW - timedelta(days=20), NOW)
    result = validate_batch(batch, Timeframe.M15, now=NOW)
    assert result.rejected == {}
    assert len(result.batch) == len(batch) > 0
    assert (np.diff(batch.ts) > 0).all()
    assert (batch.volume >= 0).all() and (batch.spread > 0).all()


@pytest.mark.parametrize(
    "timeframe", [t for t in Timeframe if t is not Timeframe.M1], ids=lambda t: t.value
)
def test_higher_timeframes_are_exact_aggregations_of_m1(
    connector: SyntheticConnector, timeframe: Timeframe
) -> None:
    start = datetime(2026, 9, 7, tzinfo=UTC)  # segunda-feira
    end = datetime(2026, 10, 5, tzinfo=UTC)
    m1 = connector.fetch_candles("EURUSD", Timeframe.M1, start, end)
    direct = connector.fetch_candles("EURUSD", timeframe, start, end)
    assert len(direct) > 0
    assert_same(direct, aggregate(m1, timeframe))
    assert all(is_aligned(int(t), timeframe) for t in direct.ts)


def test_price_path_is_continuous(connector: SyntheticConnector) -> None:
    batch = connector.fetch_candles("US500", Timeframe.M1, NOW - timedelta(days=2), NOW)
    np.testing.assert_array_equal(batch.open[1:], batch.close[:-1])


def test_weekend_closed_except_crypto(connector: SyntheticConnector) -> None:
    start, end = NOW - timedelta(days=30), NOW
    weekday = lambda b: (b.ts // 86_400 + 3) % 7  # noqa: E731 — 0 = segunda
    forex = connector.fetch_candles("EURUSD", Timeframe.H1, start, end)
    crypto = connector.fetch_candles("BTCUSD", Timeframe.H1, start, end)
    assert weekday(forex).max() == 4
    assert set(weekday(crypto).tolist()) == set(range(7))


@pytest.mark.parametrize("timeframe", list(Timeframe), ids=lambda t: t.value)
def test_never_returns_unclosed_or_future_candles(
    connector: SyntheticConnector, timeframe: Timeframe
) -> None:
    future = NOW + timedelta(days=30)
    batch = connector.fetch_candles("ETHUSD", timeframe, NOW - timedelta(days=60), future)
    size = TIMEFRAME_SECONDS[timeframe]
    assert len(batch) > 0
    assert int(batch.ts[-1]) + size <= to_epoch(NOW)
    # O último candle devolvido é exatamente o último já fechado.
    assert int(batch.ts[-1]) == floor_ts(to_epoch(NOW), timeframe) - size


def test_candle_does_not_change_after_time_passes() -> None:
    """Sem repintura: um candle fechado é idêntico quando consultado mais tarde."""
    start, end = NOW - timedelta(days=3), NOW.replace(minute=0, second=0)
    early = SyntheticConnector(now=lambda: NOW).fetch_candles("GER40", Timeframe.M30, start, end)
    later_now = NOW + timedelta(days=90)
    later = SyntheticConnector(now=lambda: later_now).fetch_candles(
        "GER40", Timeframe.M30, start, end
    )
    assert len(early) > 100
    assert_same(early, later)


def test_prices_stay_in_a_plausible_range(connector: SyntheticConnector) -> None:
    for symbol, profile in PROFILES.items():
        batch = connector.fetch_candles(symbol, Timeframe.D1, NOW - timedelta(days=4000), NOW)
        ratio = batch.close / profile.start_price
        assert 0.05 < ratio.min() and ratio.max() < 25, symbol


def test_regimes_produce_varying_volatility(connector: SyntheticConnector) -> None:
    batch = connector.fetch_candles("NAS100", Timeframe.D1, NOW - timedelta(days=1500), NOW)
    returns = np.diff(np.log(batch.close))
    blocks = [returns[i : i + 20].std() for i in range(0, len(returns) - 20, 20)]
    assert max(blocks) > 2 * min(blocks)


def test_unknown_symbol_and_empty_window(connector: SyntheticConnector) -> None:
    with pytest.raises(ConnectorError):
        connector.fetch_candles("NAOEXISTE", Timeframe.H1, NOW - timedelta(days=1), NOW)
    assert len(connector.fetch_candles("EURUSD", Timeframe.H1, NOW, NOW - timedelta(days=1))) == 0
    ancient = datetime(2000, 1, 1, tzinfo=UTC)
    assert len(connector.fetch_candles("EURUSD", Timeframe.D1, ancient, ancient)) == 0


@pytest.mark.performance
def test_generation_speed(connector: SyntheticConnector) -> None:
    started = time.perf_counter()
    batch = connector.fetch_candles("USDJPY", Timeframe.M1, NOW - timedelta(days=365), NOW)
    elapsed = time.perf_counter() - started
    assert len(batch) > 350_000
    assert elapsed < 5, f"1 ano de M1 levou {elapsed:.2f}s"
