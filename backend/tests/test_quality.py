"""Validação de entrada e avaliação de qualidade das séries."""

from datetime import UTC, datetime, timedelta

import numpy as np

from app.market.candles import CandleBatch
from app.market.connectors.synthetic import SyntheticConnector
from app.market.quality import assess_quality, validate_batch
from app.market.timeframes import to_epoch
from app.models.enums import Timeframe

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
H1 = 3600


def make_batch(n: int = 10, start: datetime = datetime(2026, 11, 2, tzinfo=UTC)) -> CandleBatch:
    ts = to_epoch(start) + np.arange(n, dtype=np.int64) * H1
    close = 100.0 + np.arange(n, dtype=np.float64)
    return CandleBatch(
        ts=ts,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=np.full(n, 10.0),
        spread=np.full(n, 0.1),
    )


def test_valid_batch_passes_untouched() -> None:
    result = validate_batch(make_batch(), Timeframe.H1, now=NOW)
    assert result.rejected == {} and len(result.batch) == result.rows_read == 10


def test_each_kind_of_invalid_row_is_rejected_and_counted() -> None:
    batch = make_batch(10)
    batch.high[1] = batch.close[1] - 5  # máxima abaixo do fechamento
    batch.low[2] = batch.open[2] + 5  # mínima acima da abertura
    batch.open[3] = np.nan
    batch.close[4] = -1.0
    batch.low[4] = -2.0
    batch.volume[5] = -3.0
    batch.ts[6] += 17  # fora da grade de 1 hora

    result = validate_batch(batch, Timeframe.H1, now=NOW)
    assert result.rejected == {
        "valor_nao_numerico": 1,
        "preco_nao_positivo": 1,
        "ohlc_inconsistente": 2,
        "volume_negativo": 1,
        "horario_desalinhado": 1,
    }
    assert result.rows_rejected == 6 and len(result.batch) == 4
    # As linhas boas não são alteradas.
    assert result.batch.close.tolist() == [100.0, 107.0, 108.0, 109.0]


def test_unclosed_candles_are_rejected_to_prevent_lookahead() -> None:
    batch = make_batch(4, start=NOW - timedelta(hours=2))  # 10h, 11h, 12h (em formação), 13h
    result = validate_batch(batch, Timeframe.H1, now=NOW + timedelta(minutes=30))
    assert result.rejected == {"candle_nao_fechado": 2}
    assert len(result.batch) == 2


def test_duplicates_keep_last_and_output_is_sorted() -> None:
    a = make_batch(3)
    shuffled = CandleBatch.concat([a.select(np.array([2, 0, 1])), a.select(np.array([0]))])
    shuffled.close[3] = 100.25  # segunda versão do primeiro candle
    result = validate_batch(shuffled, Timeframe.H1, now=NOW)
    assert result.rejected == {"horario_duplicado": 1}
    assert result.batch.ts.tolist() == a.ts.tolist()
    assert result.batch.close[0] == 100.25


def test_clean_synthetic_series_scores_100() -> None:
    connector = SyntheticConnector(now=lambda: NOW)
    for symbol, always_open in (("EURUSD", False), ("BTCUSD", True)):
        for timeframe in (Timeframe.M5, Timeframe.H1, Timeframe.D1, Timeframe.W1):
            batch = connector.fetch_candles(symbol, timeframe, NOW - timedelta(days=120), NOW)
            report = assess_quality(batch, timeframe, always_open=always_open, now=NOW)
            assert report.issues == [], (symbol, timeframe, report.issues)
            assert report.score == 100 and report.completeness_pct == 100.0
            assert not report.is_stale


def test_gaps_are_detected_with_examples() -> None:
    connector = SyntheticConnector(now=lambda: NOW)
    batch = connector.fetch_candles("BTCUSD", Timeframe.H1, NOW - timedelta(days=10), NOW)
    keep = np.ones(len(batch), dtype=bool)
    keep[50:62] = False
    report = assess_quality(batch.select(keep), Timeframe.H1, always_open=True, now=NOW)
    gap = next(i for i in report.issues if i.code == "lacunas")
    assert gap.count == 12 and gap.severity == "warning"
    assert gap.examples[0] == datetime.fromtimestamp(int(batch.ts[50]), tz=UTC)
    assert report.completeness_pct == 95.0 and report.score < 100


def test_weekend_is_not_a_gap_for_closed_markets_but_is_for_crypto() -> None:
    connector = SyntheticConnector(now=lambda: NOW)
    forex = connector.fetch_candles("EURUSD", Timeframe.H1, NOW - timedelta(days=14), NOW)
    as_forex = assess_quality(forex, Timeframe.H1, always_open=False, now=NOW)
    as_crypto = assess_quality(forex, Timeframe.H1, always_open=True, now=NOW)
    assert not any(i.code == "lacunas" for i in as_forex.issues)
    assert next(i for i in as_crypto.issues if i.code == "lacunas").count == 96  # 2 fins de semana


def test_outlier_stale_and_missing_volume_are_flagged() -> None:
    connector = SyntheticConnector(now=lambda: NOW)
    batch = connector.fetch_candles("XAUUSD", Timeframe.H1, NOW - timedelta(days=30), NOW)
    batch.close[100] *= 1.5
    batch.high[100] = max(batch.high[100], batch.close[100])
    batch.volume[:] = 0.0
    much_later = NOW + timedelta(days=10)
    report = assess_quality(batch, Timeframe.H1, always_open=False, now=much_later)
    codes = {i.code: i for i in report.issues}
    assert {"variacao_anomala", "dados_atrasados", "sem_volume"} <= set(codes)
    assert codes["variacao_anomala"].count == 2  # o salto e o retorno
    assert report.is_stale and codes["dados_atrasados"].severity == "critical"
    assert report.score <= 60


def test_empty_series() -> None:
    report = assess_quality(CandleBatch.empty(), Timeframe.H1, always_open=True, now=NOW)
    assert report.score == 0 and report.is_stale
    assert [i.code for i in report.issues] == ["sem_dados"]
