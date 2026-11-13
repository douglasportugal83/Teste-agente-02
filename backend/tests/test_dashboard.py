from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.services.seed import seed_reference_data
from tests.conftest import login, register


def test_health_and_system_info(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok", "database": "ok"}
    info = client.get("/api/v1/system/info").json()
    assert info["trading_mode"] == "simulation"
    assert info["real_orders_enabled"] is False
    assert "simulação" in info["disclaimer"]


def test_overview_for_new_user(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/dashboard/overview", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()

    assert body["monitored_symbols"] == 13
    categories = {c["category"]: c for c in body["market_by_category"]}
    assert set(categories) == {"metals", "indices", "crypto", "forex"}
    assert categories["metals"]["symbols"] == ["XAGUSD", "XAUUSD"]
    assert categories["forex"]["count"] == 5

    kinds = {c["kind"]: c["status"] for c in body["connections"]}
    assert kinds == {
        "database": "connected",
        "synthetic": "not_configured",
        "mt5": "not_configured",
    }

    simulator = body["simulator"]
    assert simulator["status"] == "paused"
    assert simulator["initial_balance"] == simulator["equity"] == 100_000
    assert simulator["pnl"] == 0 and simulator["open_positions"] == 0

    assert body["unread_alerts"] == 1
    assert body["recent_alerts"][0]["title"].startswith("Bem-vindo")
    assert len(body["equity_curve"]) == 1


def test_seed_is_idempotent(client: TestClient, db: Session, admin_headers: dict[str, str]) -> None:
    seed_reference_data(db)
    seed_reference_data(db)
    symbols = client.get("/api/v1/symbols", headers=admin_headers).json()
    assert len(symbols) == 13
    forex = client.get("/api/v1/symbols?category=forex", headers=admin_headers).json()
    assert {s["name"] for s in forex} == {"EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD"}
    sources = client.get("/api/v1/data-sources", headers=admin_headers).json()
    assert len(sources) == 2 and all(s["read_only"] for s in sources)


def test_user_isolation(client: TestClient, trader_headers: dict[str, str]) -> None:
    """Um usuário não enxerga nem altera dados de outro."""
    register(client, "outro@example.com")
    other_headers = login(client, "outro@example.com")

    mine = client.get("/api/v1/alerts", headers=trader_headers).json()
    theirs = client.get("/api/v1/alerts", headers=other_headers).json()
    assert len(mine) == len(theirs) == 1 and mine[0]["id"] != theirs[0]["id"]

    stolen = client.post(f"/api/v1/alerts/{theirs[0]['id']}/read", headers=trader_headers)
    assert stolen.status_code == 404
    assert client.get("/api/v1/alerts?unread_only=true", headers=other_headers).json() != []

    own = client.post(f"/api/v1/alerts/{mine[0]['id']}/read", headers=trader_headers)
    assert own.status_code == 200 and own.json()["is_read"] is True
    assert client.get("/api/v1/alerts?unread_only=true", headers=trader_headers).json() == []

    my_accounts = client.get("/api/v1/simulation/accounts", headers=trader_headers).json()
    their_accounts = client.get("/api/v1/simulation/accounts", headers=other_headers).json()
    assert len(my_accounts) == len(their_accounts) == 1
    assert my_accounts[0]["id"] != their_accounts[0]["id"]
    assert my_accounts[0]["is_virtual"] is True

    my_rules = client.get("/api/v1/risk/rules", headers=trader_headers).json()
    assert len(my_rules) == 7
    assert {r["account_id"] for r in my_rules} == {my_accounts[0]["id"]}


def test_websocket_status_requires_auth(client: TestClient, admin_headers: dict[str, str]) -> None:
    token = admin_headers["Authorization"].split()[1]
    with client.websocket_connect("/ws/status") as ws:
        ws.send_json({"type": "auth", "token": token})
        message = ws.receive_json()
        assert message["type"] == "status" and message["trading_mode"] == "simulation"

    with client.websocket_connect("/ws/status") as ws:
        ws.send_json({"type": "auth", "token": "invalido"})
        try:
            ws.receive_json()
            raise AssertionError("conexão deveria ter sido encerrada")
        except Exception as exc:  # noqa: BLE001
            assert type(exc).__name__ == "WebSocketDisconnect"


def test_no_real_order_execution_surface() -> None:
    """Garantia estrutural: a API não expõe rotas de execução real nem importa o MT5."""
    import sys

    paths = [getattr(r, "path", "") for r in create_app().routes]
    forbidden = ("order_send", "live", "broker", "real")
    assert not [p for p in paths if any(word in p.lower() for word in forbidden)]
    assert "MetaTrader5" not in sys.modules
