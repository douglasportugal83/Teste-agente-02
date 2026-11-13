"""Gerador determinístico de candles sintéticos.

NÃO são cotações reais: servem para desenvolver e testar o sistema sem fonte externa.

Propriedades garantidas (e cobertas por testes):
- Determinismo: o mesmo (símbolo, timeframe, intervalo) produz sempre os mesmos candles,
  em qualquer máquina e em qualquer ordem de chamada.
- Coerência entre timeframes: tudo é agregado a partir da mesma série M1, então um H1 é
  exatamente a agregação dos seus 60 M1.
- Sem look-ahead: só são devolvidos candles já fechados em relação a `now`.

Modelo: o log-preço diário segue um passeio aleatório com leve reversão à média e regimes
(tendência de alta/baixa, lateral, volatilidade elevada) que mudam a cada ~20 dias. Dentro
do dia, os retornos por minuto têm sazonalidade de sessão (Londres/Nova York mais voláteis).
Simplificação assumida: mercados que não são 24/7 fecham sábado e domingo inteiros (UTC).
"""

import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np

from app.market.candles import CandleBatch, FloatArray
from app.market.connectors.base import ConnectorError, SymbolInfo
from app.market.timeframes import TIMEFRAME_SECONDS, bucket_origin, floor_ts, to_epoch
from app.models.enums import AssetCategory, DataSourceKind, Timeframe
from app.services.catalog import DEFAULT_SYMBOLS

DAY = 86_400
MINUTES = 1_440
# Dia 0 = segunda-feira 2014-12-29. Blocos de geração têm 8 semanas e começam na segunda,
# de modo que nenhum candle (inclusive W1) atravessa a fronteira de um bloco.
EPOCH_TS = int(datetime(2014, 12, 29, tzinfo=UTC).timestamp())
HORIZON_DAYS = 31_024  # até ~2099
CHUNK_DAYS = 56
REGIME_DAYS = 20
MEAN_REVERSION = 0.002


@dataclass(frozen=True)
class Profile:
    start_price: float
    annual_vol: float
    spread: float  # em unidades de preço
    digits: int
    always_open: bool
    base_volume: float  # volume médio por minuto


PROFILES: dict[str, Profile] = {
    "XAUUSD": Profile(2000.0, 0.16, 0.30, 2, False, 120),
    "XAGUSD": Profile(24.0, 0.28, 0.03, 3, False, 80),
    "NAS100": Profile(16000.0, 0.22, 1.5, 1, False, 150),
    "US30": Profile(36000.0, 0.16, 2.5, 1, False, 110),
    "US500": Profile(4600.0, 0.17, 0.6, 1, False, 140),
    "GER40": Profile(16500.0, 0.19, 1.8, 1, False, 90),
    "BTCUSD": Profile(42000.0, 0.60, 15.0, 2, True, 60),
    "ETHUSD": Profile(2300.0, 0.75, 1.2, 2, True, 70),
    "EURUSD": Profile(1.09, 0.07, 0.00008, 5, False, 200),
    "GBPUSD": Profile(1.27, 0.09, 0.00012, 5, False, 170),
    "USDJPY": Profile(145.0, 0.10, 0.012, 3, False, 180),
    "USDCAD": Profile(1.35, 0.07, 0.00015, 5, False, 120),
    "AUDUSD": Profile(0.66, 0.10, 0.00010, 5, False, 130),
}


def _seed(symbol: str) -> int:
    return zlib.crc32(symbol.encode("utf-8"))


def _intraday_weights(always_open: bool) -> FloatArray:
    """Volatilidade relativa por minuto do dia (UTC); média quadrática = 1."""
    hours = np.arange(MINUTES) / 60.0
    london = np.exp(-0.5 * ((hours - 8.5) / 2.0) ** 2)
    new_york = np.exp(-0.5 * ((hours - 14.5) / 2.0) ** 2)
    weights = (0.75 if always_open else 0.45) + london + 1.2 * new_york
    return np.asarray(weights / np.sqrt(np.mean(weights**2)), dtype=np.float64)


@lru_cache(maxsize=64)
def _daily_path(symbol: str) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Para cada dia do horizonte: log-preço de abertura, retorno do dia e volatilidade do dia."""
    profile = PROFILES[symbol]
    rng = np.random.default_rng([_seed(symbol), 0xDA117])
    days = np.arange(HORIZON_DAYS)
    is_open = np.ones(HORIZON_DAYS, dtype=bool) if profile.always_open else (days % 7) < 5
    open_days_per_year = 365 if profile.always_open else 260
    base_vol = profile.annual_vol / np.sqrt(open_days_per_year)

    # Regimes: 0 alta, 1 baixa, 2 lateral, 3 volatilidade elevada.
    blocks = HORIZON_DAYS // REGIME_DAYS + 1
    regime = rng.choice(4, size=blocks, p=[0.25, 0.25, 0.35, 0.15])
    drift_by_regime = np.array([0.35, -0.35, 0.0, 0.0]) * base_vol
    vol_by_regime = np.array([0.9, 0.9, 0.6, 1.8])
    day_regime = np.repeat(regime, REGIME_DAYS)[:HORIZON_DAYS]
    drift = drift_by_regime[day_regime]
    vol = base_vol * vol_by_regime[day_regime]
    shocks = rng.standard_normal(HORIZON_DAYS)

    anchor = np.empty(HORIZON_DAYS)
    returns = np.zeros(HORIZON_DAYS)
    mean = level = float(np.log(profile.start_price))
    for d in range(HORIZON_DAYS):
        anchor[d] = level
        if is_open[d]:
            returns[d] = drift[d] + MEAN_REVERSION * (mean - level) + vol[d] * shocks[d]
            level += returns[d]
    vol = np.where(is_open, vol, 0.0)
    return anchor, returns, vol


def _generate_chunk(symbol: str, chunk: int) -> CandleBatch:
    """Candles M1 de um bloco de 8 semanas."""
    profile = PROFILES[symbol]
    anchor, returns, vol = _daily_path(symbol)
    first_day = chunk * CHUNK_DAYS
    days = np.arange(first_day, min(first_day + CHUNK_DAYS, HORIZON_DAYS))
    open_mask = vol[days] > 0
    days = days[open_mask]
    if days.size == 0:
        return CandleBatch.empty()

    rng = np.random.default_rng([_seed(symbol), chunk])
    n = days.size
    weights = _intraday_weights(profile.always_open)
    shocks = rng.standard_normal((n, MINUTES))
    minute_vol = (vol[days] / np.sqrt(MINUTES))[:, None] * weights[None, :]
    steps = shocks * minute_vol
    # Ponte: os retornos por minuto somam exatamente o retorno do dia.
    steps += ((returns[days] - steps.sum(axis=1)) / MINUTES)[:, None]

    log_close = anchor[days][:, None] + np.cumsum(steps, axis=1)
    log_open = np.concatenate([anchor[days][:, None], log_close[:, :-1]], axis=1)
    wick_up = np.abs(rng.standard_normal((n, MINUTES))) * minute_vol * 0.6
    wick_down = np.abs(rng.standard_normal((n, MINUTES))) * minute_vol * 0.6

    digits = profile.digits
    open_ = np.round(np.exp(log_open), digits)
    close = np.round(np.exp(log_close), digits)
    high = np.round(np.exp(np.maximum(log_open, log_close) + wick_up), digits)
    low = np.round(np.exp(np.minimum(log_open, log_close) - wick_down), digits)

    activity = (1.0 + 2.5 * np.abs(shocks)) * weights[None, :] ** 2
    volume = np.round(profile.base_volume * activity * rng.lognormal(0.0, 0.3, (n, MINUTES)))
    # Spread mais largo nas horas de menor liquidez.
    spread = np.round(profile.spread * (1.0 + 0.6 * (weights < 0.7)), digits + 1)
    spread = np.broadcast_to(spread[None, :], (n, MINUTES))

    ts = (EPOCH_TS + days * DAY)[:, None] + np.arange(MINUTES)[None, :] * 60
    return CandleBatch(
        ts.ravel().astype(np.int64),
        open_.ravel(),
        high.ravel(),
        low.ravel(),
        close.ravel(),
        volume.ravel(),
        np.ascontiguousarray(spread).ravel(),
    )


def aggregate(batch: CandleBatch, timeframe: Timeframe) -> CandleBatch:
    """Agrega candles ordenados para um timeframe maior (abertura do 1º, fechamento do último)."""
    if timeframe is Timeframe.M1 or len(batch) == 0:
        return batch
    size, origin = TIMEFRAME_SECONDS[timeframe], bucket_origin(timeframe)
    bucket = (batch.ts - origin) // size
    starts = np.flatnonzero(np.diff(bucket, prepend=bucket[0] - 1))
    ends = np.append(starts[1:], len(batch)) - 1
    counts = (ends - starts + 1).astype(np.float64)
    return CandleBatch(
        bucket[starts] * size + origin,
        batch.open[starts],
        np.maximum.reduceat(batch.high, starts),
        np.minimum.reduceat(batch.low, starts),
        batch.close[ends],
        np.add.reduceat(batch.volume, starts),
        np.add.reduceat(batch.spread, starts) / counts,
    )


class SyntheticConnector:
    kind = DataSourceKind.SYNTHETIC

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def discover_symbols(self) -> list[SymbolInfo]:
        infos = []
        for name, description, category, base, quote, digits in DEFAULT_SYMBOLS:
            if name in PROFILES:
                infos.append(
                    SymbolInfo(
                        name=name,
                        canonical_name=name,
                        category=category,
                        description=description,
                        base_currency=base,
                        quote_currency=quote,
                        digits=digits,
                        monitor_by_default=True,
                    )
                )
        return infos

    def fetch_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> CandleBatch:
        if symbol not in PROFILES:
            raise ConnectorError(f"Símbolo sintético desconhecido: {symbol}")
        size = TIMEFRAME_SECONDS[timeframe]
        now_ts = to_epoch(self._now())
        start_ts = max(to_epoch(start), EPOCH_TS)
        end_ts = min(to_epoch(end), EPOCH_TS + HORIZON_DAYS * DAY)
        # Só candles fechados: abertura + duração <= agora.
        closed_before = floor_ts(now_ts, timeframe)
        if end_ts <= start_ts or closed_before <= start_ts:
            return CandleBatch.empty()

        first_chunk = (floor_ts(start_ts, timeframe) - EPOCH_TS) // (CHUNK_DAYS * DAY)
        last_chunk = (min(end_ts, closed_before) - 1 - EPOCH_TS) // (CHUNK_DAYS * DAY)
        parts = []
        for chunk in range(max(first_chunk, 0), last_chunk + 1):
            part = aggregate(_generate_chunk(symbol, chunk), timeframe)
            keep = (part.ts >= start_ts) & (part.ts < end_ts) & (part.ts + size <= closed_before)
            parts.append(part.select(keep))
        return CandleBatch.concat(parts)


def category_is_always_open(category: AssetCategory) -> bool:
    return category is AssetCategory.CRYPTO
