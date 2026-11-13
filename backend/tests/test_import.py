"""Importação de históricos CSV/Parquet: formatos, fusos, validação e idempotência."""

import io
from datetime import UTC, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.market.connectors.file_import import ImportFormatError, parse_candle_file
from app.market.timeframes import to_epoch
from app.models import AuditLog, MarketCandle

GENERIC_CSV = b"""timestamp,open,high,low,close,volume
2026-03-02 10:00:00,1.1000,1.1010,1.0990,1.1005,150
2026-03-02 11:00:00,1.1005,1.1020,1.1000,1.1015,180
2026-03-02 12:00:00,1.1015,1.1030,1.1010,1.1025,90
"""

# Formato "Exportar barras" do MetaTrader 5: tabulações, data com pontos, colunas entre <>.
MT5_EXPORT = (
    b"<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
    b"2026.03.02\t10:00:00\t2050.10\t2052.40\t2049.80\t2051.90\t310\t0\t25\n"
    b"2026.03.02\t11:00:00\t2051.90\t2053.00\t2050.50\t2052.20\t280\t0\t27\n"
)


def at(*args: int) -> int:
    return to_epoch(datetime(*args, tzinfo=UTC))


def upload(
    client: TestClient,
    headers: dict[str, str],
    content: bytes,
    filename: str = "dados.csv",
    **fields: str,
) -> object:
    data = {"symbol": "EURUSD", "timeframe": "H1", **fields}
    return client.post(
        "/api/v1/admin/market/import",
        headers=headers,
        data=data,
        files={"file": (filename, content, "application/octet-stream")},
    )


# --- leitura de arquivos ----------------------------------------------------------------


def test_parse_generic_csv() -> None:
    batch = parse_candle_file(GENERIC_CSV, "eurusd.csv")
    assert batch.ts.tolist() == [at(2026, 3, 2, 10), at(2026, 3, 2, 11), at(2026, 3, 2, 12)]
    assert batch.close.tolist() == [1.1005, 1.1015, 1.1025]
    assert batch.volume.tolist() == [150.0, 180.0, 90.0]


def test_parse_mt5_export_format() -> None:
    batch = parse_candle_file(MT5_EXPORT, "XAUUSD_H1.csv")
    assert batch.ts.tolist() == [at(2026, 3, 2, 10), at(2026, 3, 2, 11)]
    assert batch.open.tolist() == [2050.10, 2051.90]
    assert batch.volume.tolist() == [310.0, 280.0]  # volume de ticks
    assert batch.spread.tolist() == [25.0, 27.0]


def test_parse_semicolon_separator_and_portuguese_headers() -> None:
    content = b"Data;Abertura;Maxima;Minima;Fechamento\n2026-03-02 10:00;10;12;9;11\n"
    batch = parse_candle_file(content, "x.csv")
    assert batch.ts.tolist() == [at(2026, 3, 2, 10)]
    assert (batch.open[0], batch.high[0], batch.low[0], batch.close[0]) == (10, 12, 9, 11)
    assert batch.volume.tolist() == [0.0]


def test_parse_epoch_seconds_and_milliseconds() -> None:
    ts = at(2026, 3, 2, 10)
    seconds = f"time,open,high,low,close\n{ts},1,2,0.5,1.5\n".encode()
    millis = f"time,open,high,low,close\n{ts * 1000},1,2,0.5,1.5\n".encode()
    assert parse_candle_file(seconds, "a.csv").ts.tolist() == [ts]
    assert parse_candle_file(millis, "a.csv").ts.tolist() == [ts]


def test_parquet_roundtrip_with_timezone_aware_column() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-03-02 10:00", "2026-03-02 11:00"]).tz_localize(
                "America/Sao_Paulo"
            ),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10, 20],
        }
    )
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    batch = parse_candle_file(buffer.getvalue(), "serie.parquet", source_tz="UTC")
    # A coluna já tem fuso (UTC-3): o parâmetro source_tz não a desloca de novo.
    assert batch.ts.tolist() == [at(2026, 3, 2, 13), at(2026, 3, 2, 14)]


def test_source_timezone_conversion_respects_daylight_saving() -> None:
    content = (
        b"time,open,high,low,close\n"
        b"2026-01-15 10:00,1,2,0.5,1.5\n"  # inverno em Atenas: UTC+2
        b"2026-07-15 10:00,1,2,0.5,1.5\n"  # verão em Atenas: UTC+3
    )
    batch = parse_candle_file(content, "a.csv", source_tz="Europe/Athens")
    assert batch.ts.tolist() == [at(2026, 1, 15, 8), at(2026, 7, 15, 7)]


def test_nonexistent_local_time_is_an_error_not_a_silent_shift() -> None:
    # 29/03/2026 03:30 não existe em Atenas (o relógio salta de 03:00 para 04:00).
    content = b"time,open,high,low,close\n2026-03-29 03:30,1,2,0.5,1.5\n"
    with pytest.raises(ImportFormatError, match="inexistente ou ambígua"):
        parse_candle_file(content, "a.csv", source_tz="Europe/Athens")


@pytest.mark.parametrize(
    ("content", "filename", "tz", "message"),
    [
        (b"time,open,high\n2026-01-01,1,2\n", "a.csv", "UTC", "Colunas obrigatórias ausentes"),
        (b"time,open,high,low,close\n", "a.csv", "UTC", "não contém linhas"),
        (GENERIC_CSV, "a.xlsx", "UTC", "Formato não suportado"),
        (GENERIC_CSV, "a.csv", "Marte/Olympus", "Fuso horário desconhecido"),
        (b"isto nao e parquet", "a.parquet", "UTC", "Não foi possível ler"),
        (b"time,open,high,low,close\nontem,1,2,0.5,1.5\n", "a.csv", "UTC", "data/hora inválida"),
    ],
)
def test_unreadable_files_are_rejected_with_clear_message(
    content: bytes, filename: str, tz: str, message: str
) -> None:
    with pytest.raises(ImportFormatError, match=message):
        parse_candle_file(content, filename, tz)


# --- endpoint ---------------------------------------------------------------------------


def test_import_csv_end_to_end(
    client: TestClient, db: Session, admin_headers: dict[str, str]
) -> None:
    response = upload(client, admin_headers, GENERIC_CSV, source_timezone="UTC")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["rows_read"] == report["rows_imported"] == 3
    assert report["rows_rejected"] == 0
    assert report["first_ts"].startswith("2026-03-02T10:00:00")
    assert report["quality"]["candles"] == 3
    # Um histórico antigo é corretamente apontado como desatualizado.
    assert report["quality"]["is_stale"] is True

    series = client.get(
        f"/api/v1/market/candles?symbol_id={report['symbol_id']}&timeframe=H1",
        headers=admin_headers,
    ).json()
    assert series["source_kind"] == "csv" and series["is_synthetic"] is False
    assert series["notice"] is None and series["digits"] == 4
    assert [c["c"] for c in series["candles"]] == [1.1005, 1.1015, 1.1025]
    assert series["candles"][0]["t"] == at(2026, 3, 2, 10)

    sources = client.get("/api/v1/data-sources", headers=admin_headers).json()
    imported = next(s for s in sources if s["kind"] == "csv")
    assert imported["status"] == "connected" and imported["read_only"] is True

    log = db.scalar(select(AuditLog).where(AuditLog.action == "market.import"))
    assert log is not None and log.details["rows_imported"] == 3


def test_reimport_is_idempotent_and_updates_values(
    client: TestClient, db: Session, admin_headers: dict[str, str]
) -> None:
    upload(client, admin_headers, GENERIC_CSV)
    corrected = GENERIC_CSV.replace(b"1.1005,150", b"1.1007,150")
    report = upload(client, admin_headers, corrected).json()
    assert report["rows_imported"] == 3
    assert db.scalar(select(func.count()).select_from(MarketCandle)) == 3
    closes = sorted(db.scalars(select(MarketCandle.close)))
    assert closes == [1.1007, 1.1015, 1.1025]


def test_invalid_rows_are_rejected_and_reported(
    client: TestClient, db: Session, admin_headers: dict[str, str]
) -> None:
    content = (
        b"time,open,high,low,close,volume\n"
        b"2026-03-02 10:00,1.10,1.11,1.09,1.105,10\n"
        b"2026-03-02 11:00,1.10,1.05,1.09,1.105,10\n"  # máxima abaixo da abertura
        b"2026-03-02 12:17,1.10,1.11,1.09,1.105,10\n"  # fora da grade H1
        b"2026-03-02 13:00,1.10,1.11,1.09,abc,10\n"  # fechamento não numérico
        b"2026-03-02 10:00,1.10,1.12,1.09,1.110,10\n"  # duplicata do primeiro
        b"2099-01-01 00:00,1.10,1.11,1.09,1.105,10\n"  # futuro
    )
    report = upload(client, admin_headers, content).json()
    assert report["rows_read"] == 6 and report["rows_imported"] == 1
    assert report["rejected_by_reason"] == {
        "valor_nao_numerico": 1,
        "ohlc_inconsistente": 1,
        "horario_desalinhado": 1,
        "candle_nao_fechado": 1,
        "horario_duplicado": 1,
    }
    stored = db.scalars(select(MarketCandle)).all()
    assert len(stored) == 1 and stored[0].close == 1.110  # prevalece a última ocorrência


def test_import_parquet_creates_separate_source(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    frame = pd.DataFrame(
        {
            "time": ["2026-03-02 00:00", "2026-03-03 00:00"],
            "open": [42000.0, 42500.0],
            "high": [43000.0, 43100.0],
            "low": [41500.0, 42100.0],
            "close": [42500.0, 42900.0],
        }
    )
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    response = upload(
        client,
        admin_headers,
        buffer.getvalue(),
        "btc.parquet",
        symbol="btcusd",
        timeframe="D1",
    )
    assert response.status_code == 200, response.text
    assert response.json()["symbol"] == "BTCUSD"
    symbols = client.get("/api/v1/symbols?category=crypto", headers=admin_headers).json()
    sources = {s["id"]: s for s in client.get("/api/v1/data-sources", headers=admin_headers).json()}
    kinds = sorted(sources[s["data_source_id"]]["kind"] for s in symbols if s["name"] == "BTCUSD")
    assert kinds == ["parquet", "synthetic"]


def test_import_errors_and_permissions(
    client: TestClient,
    admin_headers: dict[str, str],
    trader_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert upload(client, trader_headers, GENERIC_CSV).status_code == 403
    assert upload(client, {}, GENERIC_CSV).status_code == 401

    bad = upload(client, admin_headers, b"a,b\n1,2\n")
    assert bad.status_code == 422 and "Colunas obrigatórias" in bad.json()["detail"]
    assert upload(client, admin_headers, GENERIC_CSV, timeframe="M7").status_code == 422
    wrong_tz = upload(client, admin_headers, GENERIC_CSV, source_timezone="Nao/Existe")
    assert wrong_tz.status_code == 422

    monkeypatch.setattr(get_settings(), "import_max_bytes", 50)
    too_big = upload(client, admin_headers, GENERIC_CSV)
    assert too_big.status_code == 413
