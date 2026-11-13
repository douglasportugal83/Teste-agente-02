"""Terminal de mercados binários: modelo, motor determinístico, contabilidade e API."""

import json
import math

import pytest
from fastapi.testclient import TestClient

from app.binary.engine import DOWN, UP, BinaryEngine, EngineConfig
from app.binary.model import normal_cdf, prob_up, reach_usd
from app.binary.service import TerminalService, set_terminal_service
from tests.conftest import login, register

T0 = 1_800_000_000.0  # múltiplo de 300 e de 900: os mercados abrem alinhados


def run(engine: BinaryEngine, seconds: float, dt: float = 0.25) -> None:
    for _ in range(int(seconds / dt)):
        engine.step(engine.t + dt)


def test_model_probability() -> None:
    sigma = 1e-4
    assert prob_up(100, 100, 60, sigma) == pytest.approx(0.5)
    assert prob_up(101, 100, 60, sigma) > 0.5 > prob_up(99, 100, 60, sigma)
    # simetria em log-preço
    assert prob_up(100 * math.e**0.001, 100, 60, sigma) + prob_up(
        100 * math.e**-0.001, 100, 60, sigma
    ) == pytest.approx(1.0)
    # mesma distância, menos tempo → mais certeza
    assert prob_up(100.05, 100, 5, sigma) > prob_up(100.05, 100, 200, sigma)
    # no último instante o horizonte tem piso: nada de divisão por zero
    assert 0.5 < prob_up(100.0001, 100, 0, sigma) <= 1.0
    assert normal_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert reach_usd(100_000, 100, sigma) == pytest.approx(100.0)
    with pytest.raises(ValueError):
        prob_up(0, 100, 60, sigma)
    with pytest.raises(ValueError):
        prob_up(100, 100, 60, 0)


def test_engine_is_deterministic() -> None:
    a, b = BinaryEngine(start_time=T0), BinaryEngine(start_time=T0)
    run(a, 1800)
    run(b, 1800)
    assert a.snapshot() == b.snapshot()
    other = BinaryEngine(EngineConfig(seed=99), start_time=T0)
    run(other, 1800)
    assert other.spot != a.spot


def test_markets_roll_on_the_clock_and_reference_is_the_oracle() -> None:
    engine = BinaryEngine(start_time=T0)
    run(engine, 10)
    first = engine.markets[300]
    assert (first.start, first.end) == (T0, T0 + 300)
    assert engine.markets[900].end == T0 + 900
    run(engine, 300)
    second = engine.markets[300]
    assert second.id != first.id and second.start == T0 + 300
    assert second.reference > 0


def test_bot_respects_its_rules() -> None:
    config = EngineConfig()
    engine = BinaryEngine(config, start_time=T0)
    run(engine, 3 * 3600)
    fills = list(engine.fills)
    assert len(fills) > 50, "em 3 h simuladas o robô deveria ter operado"
    for fill in fills:
        assert 1.0 < fill.t_left <= config.watch_seconds
        assert fill.p_model >= config.min_leader_p
        assert fill.price <= config.max_ask
        assert fill.edge >= config.min_edge
        assert fill.usd >= 1.0
        assert fill.shares == pytest.approx(fill.usd / fill.price)
        assert fill.kind in {"ENTRY", "ADD", "HEDGE", "FLIP"}
    for record in engine.settled:
        assert record["stake"] <= config.max_stake_per_market + 1e-6
    # exatamente uma ENTRY por mercado operado
    by_market: dict[str, list[str]] = {}
    for fill in fills:
        by_market.setdefault(fill.market_id, []).append(fill.kind)
    assert all(kinds[0] == "ENTRY" and kinds.count("ENTRY") == 1 for kinds in by_market.values())


def test_settlement_accounting() -> None:
    engine = BinaryEngine(start_time=T0)
    run(engine, 3 * 3600)
    settled_fills = [f for f in engine.fills if f.pnl is not None]
    assert settled_fills
    # cada cota vencedora paga $1; a perdedora, zero
    for fill in settled_fills:
        assert fill.pnl == pytest.approx(fill.shares - fill.usd) or fill.pnl == pytest.approx(
            -fill.usd
        )
    assert engine.realized_pnl == pytest.approx(sum(f.pnl or 0.0 for f in settled_fills))
    assert engine.realized_pnl == pytest.approx(sum(r["pnl"] for r in engine.settled), abs=0.5)
    assert engine.markets_traded == len(engine.settled)
    assert engine.markets_won == sum(r["pnl"] > 0 for r in engine.settled)
    assert {r["outcome"] for r in engine.settled} <= {UP, DOWN}


def test_no_edge_without_book_lag() -> None:
    """Sem atraso do livro em relação ao modelo, a vantagem some e o robô quase não opera.

    Documenta de onde vem o lucro simulado: da premissa `book_lag_seconds`.
    """
    lagged = BinaryEngine(start_time=T0)
    instant = BinaryEngine(EngineConfig(book_lag_seconds=1e-6), start_time=T0)
    run(lagged, 2 * 3600)
    run(instant, 2 * 3600)
    assert instant.total_fills < lagged.total_fills * 0.2


def test_snapshot_is_json_and_complete() -> None:
    engine = BinaryEngine(start_time=T0)
    run(engine, 900)
    snapshot = json.loads(json.dumps(engine.snapshot()))
    assert snapshot["simulated"] is True
    market = snapshot["market"]
    assert market["label"] == "BTC 5M" and 0 <= market["seconds_left"] <= 300
    assert 0 <= market["p_up"] <= 1
    assert market["leader"] in {UP, DOWN}
    asks = [price for price, _ in market["book"]["asks"]]
    bids = [price for price, _ in market["book"]["bids"]]
    assert asks == sorted(asks) and bids == sorted(bids, reverse=True)
    assert min(asks) > max(bids)
    assert all(low <= min(o, c) and high >= max(o, c) for _, o, high, low, c in snapshot["candles"])
    assert snapshot["spot"]["oracle_age_ms"] >= 0
    assert len(snapshot["wire"]) > 0 and snapshot["wire_stats"]["bytes"] > 0
    for key in ("stats", "tape", "settled", "events", "inputs", "late_hist", "feeds", "markets"):
        assert key in snapshot


def make_service() -> TerminalService:
    clock = {"now": T0 + 600.0}
    service = TerminalService(warmup_seconds=600, clock=lambda: clock["now"])
    service.warm_up()
    return service


def test_service_warm_up_reaches_the_present() -> None:
    service = make_service()
    snapshot = service.snapshot()
    assert snapshot is not None and snapshot["ts"] == T0 + 600.0
    assert snapshot["stats"]["session_seconds"] == 600.0


def test_snapshot_route_requires_auth_and_reports_engine_state(client: TestClient) -> None:
    assert client.get("/api/v1/terminal/snapshot").status_code == 401
    register(client, "admin@example.com")
    headers = login(client, "admin@example.com")

    assert client.get("/api/v1/terminal/snapshot", headers=headers).status_code == 503

    set_terminal_service(TerminalService(clock=lambda: T0))  # ainda sem aquecer
    try:
        warming = client.get("/api/v1/terminal/snapshot", headers=headers)
        assert warming.status_code == 503 and "aquecendo" in warming.json()["detail"]
        set_terminal_service(make_service())
        ok = client.get("/api/v1/terminal/snapshot", headers=headers)
        assert ok.status_code == 200 and ok.json()["market"]["label"] == "BTC 5M"
    finally:
        set_terminal_service(None)


def test_terminal_websocket(client: TestClient) -> None:
    register(client, "admin@example.com")
    token = login(client, "admin@example.com")["Authorization"].removeprefix("Bearer ")
    set_terminal_service(make_service())
    try:
        with client.websocket_connect("/ws/terminal") as ws:
            ws.send_json({"type": "auth", "token": token})
            message = ws.receive_json()
            assert message["type"] == "snapshot" and message["data"]["simulated"] is True
        with client.websocket_connect("/ws/terminal") as ws:
            ws.send_json({"type": "auth", "token": "invalido"})
            with pytest.raises(Exception) as excinfo:  # noqa: PT011
                ws.receive_json()
            assert type(excinfo.value).__name__ == "WebSocketDisconnect"
    finally:
        set_terminal_service(None)
