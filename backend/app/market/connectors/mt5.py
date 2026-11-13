"""Conector MetaTrader 5 — EXCLUSIVAMENTE LEITURA de dados de mercado.

Roda apenas no processo-ponte (`python -m app.market.mt5_bridge`), numa máquina com o terminal
MT5 instalado (Windows). A API web nunca importa este módulo nem a biblioteca `MetaTrader5`.

Garantia de somente leitura: todo acesso à biblioteca passa por `ReadOnlyMT5`, que só expõe as
funções de consulta listadas em `ALLOWED_FUNCTIONS`. Qualquer outra — `order_send`,
`order_check`, `positions_get` etc. — levanta `ReadOnlyViolation`. Não existe opção de
configuração que amplie essa lista.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from app.market.candles import CandleBatch
from app.market.connectors.base import ConnectorError, SymbolInfo
from app.market.symbols import canonical_name, currencies, infer_category, is_default_symbol
from app.market.timeframes import TIMEFRAME_SECONDS, floor_ts, to_epoch
from app.models.enums import DataSourceKind, Timeframe

ALLOWED_FUNCTIONS = frozenset(
    {
        "initialize",
        "shutdown",
        "last_error",
        "terminal_info",
        "symbols_get",
        "symbol_info",
        # symbol_select apenas exibe o símbolo na Observação de Mercado (exigido p/ histórico).
        "symbol_select",
        "copy_rates_range",
    }
)


class ReadOnlyViolation(RuntimeError):
    """Tentativa de usar uma função do MT5 fora da lista de leitura."""


class ReadOnlyMT5:
    """Proxy que restringe a biblioteca MetaTrader5 às funções de leitura.

    É uma trava contra uso acidental ou futuro descuido no código, não uma sandbox: Python
    não impede quem deliberadamente contorne o proxy. Por isso há também o teste de
    varredura estática do código-fonte.
    """

    def __init__(self, module: Any) -> None:
        object.__setattr__(self, "_module", module)

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("TIMEFRAME_") or name in ALLOWED_FUNCTIONS:
            return getattr(object.__getattribute__(self, "_module"), name)
        raise ReadOnlyViolation(
            f"MetaTrader5.{name} não é permitido: o TraderAI Pro apenas lê dados de mercado."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise ReadOnlyViolation("O proxy do MetaTrader5 é imutável.")


def _load_library() -> Any:
    try:
        import MetaTrader5  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError as exc:
        raise ConnectorError(
            "Biblioteca MetaTrader5 não instalada. Ela só existe para Windows: "
            "rode a ponte na máquina do terminal com `pip install MetaTrader5`."
        ) from exc
    return MetaTrader5


def server_time_to_utc(server_epoch: np.ndarray, zone: ZoneInfo) -> np.ndarray:
    """O MT5 devolve o horário DO SERVIDOR da corretora codificado como se fosse epoch UTC.

    Convertemos para UTC real subtraindo o deslocamento do fuso do servidor em cada instante,
    o que trata corretamente o horário de verão.
    """
    out = np.empty_like(server_epoch)
    cache: dict[int, int] = {}
    for i, value in enumerate(server_epoch.tolist()):
        day = value // 3600  # o deslocamento só muda em horas cheias
        offset = cache.get(day)
        if offset is None:
            naive = datetime.fromtimestamp(value, tz=UTC).replace(tzinfo=None)
            delta = naive.replace(tzinfo=zone).utcoffset() or timedelta(0)
            offset = cache[day] = int(delta.total_seconds())
        out[i] = value - offset
    return out


class MT5Connector:
    kind = DataSourceKind.MT5

    def __init__(
        self,
        *,
        server_timezone: str = "UTC",
        terminal_path: str | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        library: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._mt5 = ReadOnlyMT5(library if library is not None else _load_library())
        self._zone = ZoneInfo(server_timezone)
        self._init_kwargs: dict[str, Any] = {}
        if terminal_path:
            self._init_kwargs["path"] = terminal_path
        if login is not None:
            # Use a senha de INVESTIDOR (somente leitura) da conta, nunca a senha mestre.
            self._init_kwargs.update(login=login, password=password, server=server)
        self._connected = False

    def connect(self) -> None:
        if not self._mt5.initialize(**self._init_kwargs):
            code = self._mt5.last_error()
            raise ConnectorError(f"Falha ao inicializar o terminal MT5: {code}")
        self._connected = True

    def close(self) -> None:
        if self._connected:
            self._mt5.shutdown()
            self._connected = False

    def is_alive(self) -> bool:
        info = self._mt5.terminal_info() if self._connected else None
        return bool(info is not None and getattr(info, "connected", False))

    def _require_connection(self) -> None:
        if not self._connected:
            raise ConnectorError("Conector MT5 não inicializado; chame connect().")

    def discover_symbols(self) -> list[SymbolInfo]:
        self._require_connection()
        raw = self._mt5.symbols_get()
        if raw is None:
            raise ConnectorError(f"MT5 não devolveu símbolos: {self._mt5.last_error()}")
        infos = []
        for item in raw:
            canonical = canonical_name(item.name)
            base, quote = currencies(canonical)
            infos.append(
                SymbolInfo(
                    name=item.name,
                    canonical_name=canonical,
                    category=infer_category(canonical, getattr(item, "path", "") or ""),
                    description=getattr(item, "description", None) or None,
                    base_currency=getattr(item, "currency_base", None) or base,
                    quote_currency=getattr(item, "currency_profit", None) or quote,
                    digits=int(getattr(item, "digits", 2)),
                    contract_size=float(getattr(item, "trade_contract_size", 1.0) or 1.0),
                    monitor_by_default=is_default_symbol(canonical),
                )
            )
        return infos

    def fetch_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> CandleBatch:
        self._require_connection()
        if not self._mt5.symbol_select(symbol, True):
            raise ConnectorError(f"Símbolo indisponível no terminal: {symbol}")
        info = self._mt5.symbol_info(symbol)
        point = float(getattr(info, "point", 0.0) or 0.0)

        # O intervalo pedido é ampliado em um dia para cada lado porque a API do MT5 filtra
        # pelo horário do servidor; o recorte exato é refeito abaixo, já em UTC.
        mt5_timeframe = getattr(self._mt5, f"TIMEFRAME_{timeframe.value}")
        rates = self._mt5.copy_rates_range(
            symbol, mt5_timeframe, start - timedelta(days=1), end + timedelta(days=1)
        )
        if rates is None:
            raise ConnectorError(f"MT5 não devolveu candles de {symbol}: {self._mt5.last_error()}")
        if len(rates) == 0:
            return CandleBatch.empty()

        ts = server_time_to_utc(np.asarray(rates["time"], dtype=np.int64), self._zone)
        if timeframe in (Timeframe.D1, Timeframe.W1):
            # Candles diários/semanais do servidor não começam à meia-noite UTC; são
            # normalizados para o início do período UTC correspondente.
            size = TIMEFRAME_SECONDS[Timeframe.D1]
            rounded = (ts + size // 2) // size * size
            ts = np.array([floor_ts(int(t), timeframe) for t in rounded], dtype=np.int64)
        batch = CandleBatch(
            ts=ts,
            open=np.asarray(rates["open"], dtype=np.float64),
            high=np.asarray(rates["high"], dtype=np.float64),
            low=np.asarray(rates["low"], dtype=np.float64),
            close=np.asarray(rates["close"], dtype=np.float64),
            volume=np.asarray(rates["tick_volume"], dtype=np.float64),
            spread=np.asarray(rates["spread"], dtype=np.float64) * point,
        )
        # Descarta o candle ainda em formação e o que estiver fora do intervalo pedido.
        size = TIMEFRAME_SECONDS[timeframe]
        closed_before = floor_ts(to_epoch(self._now()), timeframe)
        keep = (
            (batch.ts >= to_epoch(start))
            & (batch.ts < to_epoch(end))
            & (batch.ts + size <= closed_before)
        )
        return batch.select(keep)
