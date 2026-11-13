"""Contrato dos conectores de dados de mercado.

A interface é deliberadamente SOMENTE LEITURA: não há método de envio, alteração ou
cancelamento de ordens, e nenhum conector deve acrescentá-lo.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.market.candles import CandleBatch
from app.models.enums import AssetCategory, DataSourceKind, Timeframe


class ConnectorError(Exception):
    """Falha ao falar com a fonte (indisponível, símbolo inexistente, resposta inválida)."""


@dataclass(frozen=True)
class SymbolInfo:
    name: str  # nome na fonte (ex.: "USTEC", "EURUSD.m")
    canonical_name: str  # nome normalizado (ex.: "NAS100", "EURUSD")
    category: AssetCategory
    description: str | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    digits: int = 2
    contract_size: float = 1.0
    # True quando o ativo pertence ao catálogo padrão e deve ser monitorado ao ser descoberto.
    monitor_by_default: bool = False


class MarketDataConnector(Protocol):
    kind: DataSourceKind

    def discover_symbols(self) -> list[SymbolInfo]:
        """Símbolos disponíveis na fonte neste momento."""
        ...

    def fetch_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> CandleBatch:
        """Candles FECHADOS com abertura em [start, end). Nunca devolve candle em formação."""
        ...
