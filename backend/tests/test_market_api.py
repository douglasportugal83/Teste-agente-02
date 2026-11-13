"""Sincronização da fonte sintética e endpoints de consulta de mercado."""

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.market import service
from app.market.connectors.synthetic import SyntheticConnector
from app.market.service import DEFAULT_DEPTH
from app.market.timeframes import TIMEFRAME_SECONDS, floor_ts, to_epoch
from app.market.worker import MarketWorker, sync_synthetic_sources
from app.models import Alert, DataSource, MarketCandle, Symbol
from app.models.enums import DataSourceKind, DataSourceStatus, Timeframe
from tests.conftest import register

NOW = datetime(2026, 11, 13, 12, 7, 30, tzinfo=UTC)
# Histórico curto para manter os testes rápidos.
SHORT_DEPTH = {t: min(d, timedelta(days=5)) for t, d in DEFAULT_DEPTH.items()}
SHORT_DEPTH[Timeframe.D1] = timedelta(days=30)
SHORT_DEPTH[Timeframe.W1] = timedelta(days=60)


@pytest.fixture
def synced(db: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Banco com a fonte sintética sincronizada 'agora' (relógio real, histórico curto)."""
    monkeypatch.setattr(service, "DEFAULT_DEPTH", SHORT_DEPTH)
    sync_synthetic_sources(db)
    return db


def symbol_id(client: TestClient, headers: dict[str, str], name: str) -> str:
    symbols = client.get("/api/v1/symbols", headers=headers).json()
    return next(s["id"] for s in symbols if s["name"] == name)


def synthetic_source(db: Session) -> DataSource:
    source = db.scalar(select(DataSource).where(DataSource.kind == DataSourceKind.SYNTHETIC))
    assert source is not None
    return source


# --- sincronização ----------------------------------------------------------------------


def test_initial_sync_fills_every_series(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "DEFAULT_DEPTH", SHORT_DEPTH)
    stats = sync_synthetic_sources(db, now=NOW)
    assert stats.series == 13 * 8 and stats.rejected == 0 and stats.errors == []
    assert stats.candles == db.scalar(select(func.count()).select_from(MarketCandle))

    source = synthetic_source(db)
    assert source.status is DataSourceStatus.CONNECTED
    assert source.last_sync_at is not None and "note" not in source.config

    last = service.last_timestamps(db, source.id)
    assert len(last) == 13 * 8
    for (_, timeframe), ts in last.items():
        if timeframe is not Timeframe.W1:  # todos os mercados estavam abertos na sexta, 12:07
            assert ts == floor_ts(to_epoch(NOW), timeframe) - TIMEFRAME_SECONDS[timeframe]


def test_incremental_sync_adds_only_new_closed_candles(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "DEFAULT_DEPTH", SHORT_DEPTH)
    sync_synthetic_sources(db, now=NOW)
    total = db.scalar(select(func.count()).select_from(MarketCandle))

    assert sync_synthetic_sources(db, now=NOW + timedelta(seconds=20)).candles == 0

    # 12:10:30 — fecharam 3 candles M1 (12:07, 12:08, 12:09) e 1 candle M5 (12:05).
    stats = sync_synthetic_sources(db, now=NOW + timedelta(minutes=3))
    assert stats.candles == 13 * 3 + 13 * 1
    assert db.scalar(select(func.count()).select_from(MarketCandle)) == total + stats.candles


def test_stored_candles_match_generator_exactly(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "DEFAULT_DEPTH", SHORT_DEPTH)
    sync_synthetic_sources(db, now=NOW)
    symbol = db.scalar(select(Symbol).where(Symbol.name == "XAUUSD"))
    assert symbol is not None
    stored = service.load_candles(db, symbol.id, Timeframe.M15)
    expected = SyntheticConnector(now=lambda: NOW).fetch_candles(
        "XAUUSD", Timeframe.M15, NOW - SHORT_DEPTH[Timeframe.M15], NOW
    )
    assert stored.ts.tolist() == expected.ts.tolist()
    assert stored.close.tolist() == expected.close.tolist()
    assert stored.spread.tolist() == pytest.approx(expected.spread.tolist())


def test_unmonitored_symbols_are_skipped(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "DEFAULT_DEPTH", SHORT_DEPTH)
    symbol = db.scalar(select(Symbol).where(Symbol.name == "AUDUSD"))
    assert symbol is not None
    symbol.is_monitored = False
    db.commit()
    stats = sync_synthetic_sources(db, now=NOW)
    assert stats.series == 12 * 8
    assert service.load_candles(db, symbol.id, Timeframe.H1).ts.size == 0


def test_worker_survives_failures_and_reports_them(
    client: TestClient, db: Session, session_factory: sessionmaker[Session]
) -> None:
    register(client, "admin@example.com")
    worker = MarketWorker(session_factory, interval_seconds=60)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falha simulada do gerador")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.market.worker.sync_synthetic_sources", boom)
        worker.run_once()  # não propaga a exceção
    db.expire_all()
    source = synthetic_source(db)
    assert source.status is DataSourceStatus.ERROR
    assert source.last_error == "falha simulada do gerador"
    assert db.scalar(select(func.count()).select_from(Alert).where(Alert.category == "data")) == 1


def test_worker_thread_starts_syncs_and_stops(
    db: Session, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "DEFAULT_DEPTH", {t: timedelta(hours=6) for t in Timeframe})
    worker = MarketWorker(session_factory, interval_seconds=60)
    worker.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        db.expire_all()
        if synthetic_source(db).status is DataSourceStatus.CONNECTED:
            break
        time.sleep(0.2)
    worker.stop()
    assert synthetic_source(db).status is DataSourceStatus.CONNECTED
    assert db.scalar(select(func.count()).select_from(MarketCandle)) > 0
    assert worker._thread is not None and not worker._thread.is_alive()  # noqa: SLF001


# --- consulta ---------------------------------------------------------------------------


def test_candles_endpoint(client: TestClient, synced: Session, admin_headers: dict) -> None:
    sid = symbol_id(client, admin_headers, "EURUSD")
    response = client.get(
        f"/api/v1/market/candles?symbol_id={sid}&timeframe=M5&limit=50", headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "EURUSD" and body["timeframe"] == "M5" and body["digits"] == 5
    assert body["is_synthetic"] is True and "não são cotações reais" in body["notice"]
    candles = body["candles"]
    assert len(candles) == 50
    assert set(candles[0]) == {"t", "o", "h", "l", "c", "v"}
    times = [c["t"] for c in candles]
    assert times == sorted(times) and all(t % 300 == 0 for t in times)
    assert all(c["h"] >= max(c["o"], c["c"]) and c["l"] <= min(c["o"], c["c"]) for c in candles)
    # Nenhum candle em formação: o mais recente já fechou.
    assert times[-1] + 300 <= time.time()

    end = datetime.fromtimestamp(times[10], tz=UTC).isoformat().replace("+00:00", "Z")
    older = client.get(
        f"/api/v1/market/candles?symbol_id={sid}&timeframe=M5&end={end}&limit=5",
        headers=admin_headers,
    ).json()["candles"]
    assert [c["t"] for c in older] == times[5:10]


def test_candles_endpoint_errors(client: TestClient, synced: Session, admin_headers: dict) -> None:
    sid = symbol_id(client, admin_headers, "EURUSD")
    base = "/api/v1/market/candles"
    assert client.get(f"{base}?symbol_id={sid}").status_code == 401
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"{base}?symbol_id={missing}", headers=admin_headers).status_code == 404
    for query in (f"symbol_id={sid}&timeframe=M2", f"symbol_id={sid}&limit=999999", "symbol_id=x"):
        assert client.get(f"{base}?{query}", headers=admin_headers).status_code == 422


def test_quotes_endpoint(client: TestClient, synced: Session, admin_headers: dict) -> None:
    quotes = client.get("/api/v1/market/quotes", headers=admin_headers).json()
    assert len(quotes) == 13
    by_name = {q["name"]: q for q in quotes}
    btc = by_name["BTCUSD"]
    assert btc["price"] > 0 and btc["is_synthetic"] is True and btc["is_stale"] is False
    assert btc["change_pct"] is not None and abs(btc["change_pct"]) < 50
    assert all(q["price"] is not None for q in quotes)


def test_quotes_flag_stale_data(client: TestClient, db: Session, admin_headers: dict) -> None:
    # Sincronização "congelada" 10 dias atrás: os preços existem, mas estão atrasados.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, "DEFAULT_DEPTH", SHORT_DEPTH)
        sync_synthetic_sources(db, now=datetime.now(UTC) - timedelta(days=10))
    quotes = client.get("/api/v1/market/quotes", headers=admin_headers).json()
    assert all(q["is_stale"] for q in quotes) and all(q["price"] for q in quotes)


def test_quality_and_coverage_endpoints(
    client: TestClient, synced: Session, admin_headers: dict
) -> None:
    sid = symbol_id(client, admin_headers, "BTCUSD")
    quality = client.get(
        f"/api/v1/market/quality?symbol_id={sid}&timeframe=H1", headers=admin_headers
    ).json()
    assert quality["score"] == 100 and quality["issues"] == [] and not quality["is_stale"]
    assert quality["candles"] == quality["expected_candles"] > 100

    coverage = client.get("/api/v1/market/coverage", headers=admin_headers).json()
    assert len(coverage) == 13 * 8
    row = next(c for c in coverage if c["symbol"] == "BTCUSD" and c["timeframe"] == "H1")
    assert row["candles"] == quality["candles"] and row["source"] == "Dados sintéticos"


def test_overview_reflects_connected_source(
    client: TestClient, synced: Session, admin_headers: dict
) -> None:
    body = client.get("/api/v1/dashboard/overview", headers=admin_headers).json()
    kinds = {c["kind"]: c for c in body["connections"]}
    assert kinds["synthetic"]["status"] == "connected" and kinds["synthetic"]["detail"] is None
    assert body["monitored_symbols"] == 13


# --- administração ----------------------------------------------------------------------


def test_admin_sync_and_backfill(
    client: TestClient, db: Session, admin_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "DEFAULT_DEPTH", {t: timedelta(hours=12) for t in Timeframe})
    source_id = synthetic_source(db).id
    sync = client.post(f"/api/v1/admin/data-sources/{source_id}/sync", headers=admin_headers)
    assert sync.status_code == 200 and sync.json()["candles"] > 0

    sid = symbol_id(client, admin_headers, "GER40")
    payload = {
        "symbol_ids": [sid],
        "timeframes": ["D1"],
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-03-01T00:00:00Z",
    }
    response = client.post(
        f"/api/v1/admin/data-sources/{source_id}/backfill", json=payload, headers=admin_headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"series": 1, "candles": 44, "rejected": 0, "errors": []}
    # Repetir o pedido não duplica nada.
    client.post(
        f"/api/v1/admin/data-sources/{source_id}/backfill", json=payload, headers=admin_headers
    )
    stored = service.load_candles(
        db, uuid.UUID(sid), Timeframe.D1, end=datetime(2024, 3, 1, tzinfo=UTC)
    )
    assert len(stored) == 44  # dias úteis de jan (23) + fev (21) de 2024

    logs = client.get("/api/v1/admin/audit-logs", headers=admin_headers).json()
    assert {"market.sync", "market.backfill"} <= {entry["action"] for entry in logs}


def test_backfill_limits_and_validation(
    client: TestClient, db: Session, admin_headers: dict, trader_headers: dict
) -> None:
    sources = client.get("/api/v1/data-sources", headers=admin_headers).json()
    synthetic = next(s["id"] for s in sources if s["kind"] == "synthetic")
    mt5 = next(s["id"] for s in sources if s["kind"] == "mt5")
    url = f"/api/v1/admin/data-sources/{synthetic}/backfill"
    huge = {"timeframes": ["M1"], "start": "2016-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}
    too_many = client.post(url, json=huge, headers=admin_headers)
    assert too_many.status_code == 422 and "limite" in too_many.json()["detail"]

    inverted = {
        "timeframes": ["H1"],
        "start": "2026-02-01T00:00:00Z",
        "end": "2026-01-01T00:00:00Z",
    }
    assert client.post(url, json=inverted, headers=admin_headers).status_code == 422
    assert client.post(url, json=huge, headers=trader_headers).status_code == 403

    # A fonte MT5 só é alimentada pela ponte, nunca pela API.
    for action in ("sync", "backfill"):
        response = client.post(
            f"/api/v1/admin/data-sources/{mt5}/{action}", json=huge, headers=admin_headers
        )
        assert response.status_code == 409 and "ponte" in response.json()["detail"]


def test_toggle_symbol_monitoring(
    client: TestClient, synced: Session, admin_headers: dict, trader_headers: dict
) -> None:
    sid = symbol_id(client, admin_headers, "USDCAD")
    url = f"/api/v1/admin/symbols/{sid}"
    assert (
        client.patch(url, json={"is_monitored": False}, headers=trader_headers).status_code == 403
    )
    response = client.patch(url, json={"is_monitored": False}, headers=admin_headers)
    assert response.status_code == 200 and response.json()["is_monitored"] is False
    quotes = client.get("/api/v1/market/quotes", headers=admin_headers).json()
    assert "USDCAD" not in {q["name"] for q in quotes} and len(quotes) == 12
    assert (
        client.get("/api/v1/dashboard/overview", headers=admin_headers).json()["monitored_symbols"]
        == 12
    )


@pytest.mark.performance
def test_upsert_throughput(db: Session) -> None:
    symbol = db.scalar(select(Symbol).where(Symbol.name == "EURUSD"))
    assert symbol is not None
    batch = SyntheticConnector(now=lambda: NOW).fetch_candles(
        "EURUSD", Timeframe.M1, NOW - timedelta(days=50), NOW
    )
    assert len(batch) > 50_000
    started = time.perf_counter()
    service.upsert_candles(db, symbol.id, Timeframe.M1, batch)
    db.commit()
    first = time.perf_counter() - started
    started = time.perf_counter()
    service.upsert_candles(db, symbol.id, Timeframe.M1, batch)  # tudo em conflito
    db.commit()
    second = time.perf_counter() - started
    assert db.scalar(select(func.count()).select_from(MarketCandle)) == len(batch)
    assert first < 30 and second < 30, (
        f"upsert de {len(batch)} candles: {first:.1f}s / {second:.1f}s"
    )
