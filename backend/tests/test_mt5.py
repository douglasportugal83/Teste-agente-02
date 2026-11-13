"""Conector MT5 testado contra um terminal SIMULADO (a biblioteca real só existe no Windows).

Estes testes verificam o que é nosso: restrição a leitura, conversão de fuso, mapeamento de
símbolos e tratamento de falhas. Não substituem um teste contra um terminal real.
"""

import ast
import inspect
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.market import mt5_bridge
from app.market.connectors import mt5 as mt5_module
from app.market.connectors.base import ConnectorError
from app.market.connectors.mt5 import (
    ALLOWED_FUNCTIONS,
    MT5Connector,
    ReadOnlyMT5,
    ReadOnlyViolation,
    server_time_to_utc,
)
from app.market.timeframes import to_epoch
from app.models import Alert, DataSource, MarketCandle, Symbol
from app.models.enums import AssetCategory, DataSourceKind, DataSourceStatus, Timeframe
from tests.conftest import register

ATHENS = ZoneInfo("Europe/Athens")
NOW = datetime(2026, 11, 13, 12, 30, tzinfo=UTC)
RATES_DTYPE = [
    ("time", "i8"),
    ("open", "f8"),
    ("high", "f8"),
    ("low", "f8"),
    ("close", "f8"),
    ("tick_volume", "u8"),
    ("spread", "i4"),
    ("real_volume", "u8"),
]


def server_epoch(utc: datetime, zone: ZoneInfo = ATHENS) -> int:
    """Como o MT5 codifica um instante: horário de parede do servidor lido como se fosse UTC."""
    wall = utc.astimezone(zone).replace(tzinfo=UTC)
    return int(wall.timestamp())


class FakeMT5:
    """Imita a parte da biblioteca MetaTrader5 usada pelo conector e registra as chamadas."""

    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1, TIMEFRAME_W1 = 16385, 16388, 16408, 32769

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_initialize = False
        self.connected = True
        self.symbols = [
            SimpleNamespace(
                name="EURUSD.m",
                path="Forex\\Majors\\EURUSD.m",
                description="Euro vs US Dollar",
                currency_base="EUR",
                currency_profit="USD",
                digits=5,
                trade_contract_size=100000.0,
                point=0.00001,
            ),
            SimpleNamespace(
                name="USTEC",
                path="Indices\\USTEC",
                description="US Tech 100",
                currency_base="USD",
                currency_profit="USD",
                digits=1,
                trade_contract_size=1.0,
                point=0.1,
            ),
            SimpleNamespace(
                name="PETR4",
                path="Stocks\\Brazil\\PETR4",
                description="Petrobras PN",
                currency_base="BRL",
                currency_profit="BRL",
                digits=2,
                trade_contract_size=1.0,
                point=0.01,
            ),
        ]

    def _log(self, name: str) -> None:
        self.calls.append(name)

    def initialize(self, **kwargs: Any) -> bool:
        self._log("initialize")
        self.init_kwargs = kwargs
        return not self.fail_initialize

    def shutdown(self) -> None:
        self._log("shutdown")

    def last_error(self) -> tuple[int, str]:
        return (-10005, "IPC timeout")

    def terminal_info(self) -> Any:
        return SimpleNamespace(connected=self.connected)

    def symbols_get(self) -> Any:
        self._log("symbols_get")
        return tuple(self.symbols)

    def symbol_info(self, name: str) -> Any:
        return next((s for s in self.symbols if s.name == name), None)

    def symbol_select(self, name: str, enable: bool) -> bool:
        self._log("symbol_select")
        return any(s.name == name for s in self.symbols)

    def copy_rates_range(self, name: str, timeframe: int, start: datetime, end: datetime) -> Any:
        self._log("copy_rates_range")
        if timeframe != self.TIMEFRAME_H1:
            return np.zeros(0, dtype=RATES_DTYPE)
        # Uma barra por hora UTC, de segunda a sexta, incluindo a que ainda está em formação.
        rows = []
        cursor = start.replace(minute=0, second=0, microsecond=0)
        while cursor <= min(end, NOW):
            if cursor.weekday() < 5:
                price = 1.1 + cursor.hour / 10_000
                rows.append(
                    (server_epoch(cursor), price, price + 0.001, price - 0.001, price, 120, 12, 0)
                )
            cursor += timedelta(hours=1)
        return np.array(rows, dtype=RATES_DTYPE)

    # Funções de negociação existem na biblioteca real; aqui só para provar que são barradas.
    def order_send(self, request: Any) -> Any:
        self._log("order_send")
        raise AssertionError("order_send jamais deveria ser alcançado")

    def positions_get(self) -> Any:
        self._log("positions_get")
        raise AssertionError("positions_get jamais deveria ser alcançado")


@pytest.fixture
def fake() -> FakeMT5:
    return FakeMT5()


@pytest.fixture
def connector(fake: FakeMT5) -> MT5Connector:
    conn = MT5Connector(server_timezone="Europe/Athens", library=fake, now=lambda: NOW)
    conn.connect()
    return conn


# --- garantia de somente leitura --------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "order_send",
        "order_check",
        "order_calc_margin",
        "positions_get",
        "orders_get",
        "history_deals_get",
        "account_info",
        "login",
    ],
)
def test_trading_and_account_functions_are_blocked(fake: FakeMT5, name: str) -> None:
    proxy = ReadOnlyMT5(fake)
    with pytest.raises(ReadOnlyViolation):
        getattr(proxy, name)
    assert fake.calls == []


def test_proxy_cannot_be_tampered_with(fake: FakeMT5) -> None:
    proxy = ReadOnlyMT5(fake)
    with pytest.raises(ReadOnlyViolation):
        proxy.order_send = lambda request: None  # type: ignore[misc]
    with pytest.raises(ReadOnlyViolation):
        proxy._module  # noqa: B018 — o módulo original não é alcançável pelo proxy


def test_allowlist_contains_only_read_functions() -> None:
    assert ALLOWED_FUNCTIONS == {
        "initialize",
        "shutdown",
        "last_error",
        "terminal_info",
        "symbols_get",
        "symbol_info",
        "symbol_select",
        "copy_rates_range",
    }


def test_source_code_never_calls_order_execution() -> None:
    """Varredura estática do código executável (comentários e docstrings são ignorados)."""
    forbidden = {"order_send", "order_check", "order_calc_margin", "positions_get", "orders_get"}
    for module in (mt5_module, mt5_bridge):
        tree = ast.parse(inspect.getsource(module))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        strings = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and "\n" not in n.value
        }
        assert not forbidden & (names | strings), module.__name__


def test_connector_only_calls_read_functions(connector: MT5Connector, fake: FakeMT5) -> None:
    connector.discover_symbols()
    connector.fetch_candles("EURUSD.m", Timeframe.H1, NOW - timedelta(days=2), NOW)
    connector.close()
    assert set(fake.calls) <= ALLOWED_FUNCTIONS
    assert "order_send" not in fake.calls


def test_api_process_never_imports_metatrader5() -> None:
    assert "MetaTrader5" not in sys.modules


# --- comportamento ----------------------------------------------------------------------


def test_missing_library_gives_actionable_error() -> None:
    with pytest.raises(ConnectorError, match="Windows"):
        MT5Connector()


def test_initialize_failure_and_use_before_connect(fake: FakeMT5) -> None:
    conn = MT5Connector(library=fake)
    with pytest.raises(ConnectorError, match="não inicializado"):
        conn.discover_symbols()
    fake.fail_initialize = True
    with pytest.raises(ConnectorError, match="IPC timeout"):
        conn.connect()


def test_credentials_are_passed_only_when_configured(fake: FakeMT5) -> None:
    MT5Connector(library=fake).connect()
    assert fake.init_kwargs == {}
    MT5Connector(library=fake, login=123, password="investidor", server="Demo").connect()
    assert fake.init_kwargs == {"login": 123, "password": "investidor", "server": "Demo"}


def test_server_time_conversion_handles_dst() -> None:
    winter = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)  # Atenas = UTC+2
    summer = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)  # Atenas = UTC+3
    encoded = np.array([server_epoch(winter), server_epoch(summer)], dtype=np.int64)
    assert encoded[0] - to_epoch(winter) == 2 * 3600
    assert encoded[1] - to_epoch(summer) == 3 * 3600
    converted = server_time_to_utc(encoded, ATHENS)
    assert converted.tolist() == [to_epoch(winter), to_epoch(summer)]
    np.testing.assert_array_equal(server_time_to_utc(encoded, ZoneInfo("UTC")), encoded)


def test_symbol_discovery_normalizes_names_and_categories(connector: MT5Connector) -> None:
    infos = {i.name: i for i in connector.discover_symbols()}
    assert infos["EURUSD.m"].canonical_name == "EURUSD"
    assert infos["EURUSD.m"].category is AssetCategory.FOREX
    assert infos["EURUSD.m"].monitor_by_default
    assert infos["USTEC"].canonical_name == "NAS100"
    assert infos["USTEC"].category is AssetCategory.INDICES
    assert infos["PETR4"].category is AssetCategory.OTHER
    assert not infos["PETR4"].monitor_by_default


def test_fetch_converts_to_utc_and_drops_forming_candle(connector: MT5Connector) -> None:
    start = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
    batch = connector.fetch_candles("EURUSD.m", Timeframe.H1, start, NOW)
    assert int(batch.ts[0]) == to_epoch(start)
    # 12:00 UTC ainda está em formação às 12:30: o último devolvido é o de 11:00.
    assert int(batch.ts[-1]) == to_epoch(datetime(2026, 11, 13, 11, 0, tzinfo=UTC))
    assert len(batch) == 36
    assert batch.spread[0] == pytest.approx(12 * 0.00001)
    # O preço codifica a hora UTC original: prova de que a conversão não deslocou as barras.
    hours = np.array([datetime.fromtimestamp(int(t), tz=UTC).hour for t in batch.ts])
    np.testing.assert_allclose(batch.close, 1.1 + hours / 10_000)


def test_unknown_symbol(connector: MT5Connector) -> None:
    with pytest.raises(ConnectorError, match="indisponível"):
        connector.fetch_candles("NAOEXISTE", Timeframe.H1, NOW - timedelta(days=1), NOW)


# --- ponte: terminal simulado -> banco ---------------------------------------------------


def test_bridge_sync_stores_symbols_and_candles(
    db: Session, connector: MT5Connector, fake: FakeMT5
) -> None:
    stats = mt5_bridge.sync_once(db, connector, [Timeframe.H1], now=NOW)
    source = db.scalar(select(DataSource).where(DataSource.kind == DataSourceKind.MT5))
    assert source is not None and source.status is DataSourceStatus.CONNECTED
    assert source.read_only and source.last_error is None

    symbols = {
        s.name: s for s in db.scalars(select(Symbol).where(Symbol.data_source_id == source.id))
    }
    assert set(symbols) == {"EURUSD.m", "USTEC", "PETR4"}
    assert symbols["EURUSD.m"].is_monitored and not symbols["PETR4"].is_monitored

    stored = db.scalar(select(func.count()).select_from(MarketCandle))
    assert stats.candles == stored and stats.series == 2 and stats.rejected == 0
    assert stats.candles > 2000  # ~180 dias úteis de H1 para dois símbolos

    # Segunda passada no mesmo instante: nada novo, nada duplicado.
    again = mt5_bridge.sync_once(db, connector, [Timeframe.H1], now=NOW)
    assert again.candles == 0
    assert db.scalar(select(func.count()).select_from(MarketCandle)) == stored

    # Uma hora depois: exatamente um candle novo por símbolo monitorado.
    later = NOW + timedelta(hours=1)
    connector._now = lambda: later  # noqa: SLF001
    fake_now = mt5_bridge.sync_once(db, connector, [Timeframe.H1], now=later)
    assert fake_now.candles == 2


def test_bridge_failure_marks_source_and_alerts_admins(
    client: Any, db: Session, session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client, "admin@example.com")
    monkeypatch.setattr(mt5_bridge, "get_sessionmaker", lambda: session_factory)
    mt5_bridge.record_failure("Falha ao inicializar o terminal MT5: (-10005, 'IPC timeout')")
    mt5_bridge.record_failure("de novo")  # não gera segundo alerta enquanto continuar em erro

    db.expire_all()
    source = db.scalar(select(DataSource).where(DataSource.kind == DataSourceKind.MT5))
    assert source is not None and source.status is DataSourceStatus.ERROR
    assert source.last_error == "de novo"
    alerts = db.scalars(select(Alert).where(Alert.category == "data")).all()
    assert len(alerts) == 1 and "MetaTrader 5" in alerts[0].title


def test_bridge_run_once_success_and_failure(
    db: Session, session_factory: Any, fake: FakeMT5, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mt5_bridge, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        mt5_bridge,
        "build_connector",
        lambda: MT5Connector(server_timezone="Europe/Athens", library=fake),
    )
    assert mt5_bridge.run([Timeframe.H1], interval=None) == 0
    assert fake.calls[0] == "initialize" and fake.calls[-1] == "shutdown"
    assert db.scalar(select(func.count()).select_from(MarketCandle)) > 0

    fake.fail_initialize = True
    assert mt5_bridge.run([Timeframe.H1], interval=None) == 1
    db.expire_all()
    source = db.scalar(select(DataSource).where(DataSource.kind == DataSourceKind.MT5))
    assert source is not None and source.status is DataSourceStatus.ERROR
    assert "IPC timeout" in (source.last_error or "")


def test_bridge_loop_reconnects_with_backoff(
    db: Session, session_factory: Any, fake: FakeMT5, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal cai, a ponte registra o erro, espera e reconecta; depois volta a sincronizar."""
    monkeypatch.setattr(mt5_bridge, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        mt5_bridge,
        "build_connector",
        lambda: MT5Connector(server_timezone="Europe/Athens", library=fake),
    )
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            fake.connected = False  # o terminal perde a conexão após o 1º ciclo
        elif len(sleeps) == 2:
            fake.connected = True  # durante a espera de reconexão, a conexão volta
        elif len(sleeps) == 4:
            raise KeyboardInterrupt

    monkeypatch.setattr(mt5_bridge.time, "sleep", fake_sleep)
    assert mt5_bridge.run([Timeframe.H1], interval=30) == 0
    # ciclo ok (30s) -> queda detectada -> backoff (5s) -> reconecta -> ciclos normais (30s)
    assert sleeps == [30, 5.0, 30, 30]
    assert fake.calls.count("initialize") == 2 and fake.calls.count("shutdown") == 2
    db.expire_all()
    source = db.scalar(select(DataSource).where(DataSource.kind == DataSourceKind.MT5))
    assert source is not None and source.status is DataSourceStatus.CONNECTED
