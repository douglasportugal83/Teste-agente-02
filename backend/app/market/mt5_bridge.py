"""Ponte MetaTrader 5 → banco de dados (SOMENTE LEITURA do terminal).

Processo separado da API, para rodar na máquina Windows onde o terminal MT5 está instalado:

    pip install -e ".[mt5]"
    python -m app.market.mt5_bridge --once            # uma sincronização
    python -m app.market.mt5_bridge --interval 30     # contínuo, com reconexão

Lê símbolos e candles do terminal e grava no mesmo banco da API (DATABASE_URL). Não envia,
altera nem consulta ordens: ver `ReadOnlyMT5` em connectors/mt5.py.
"""

import argparse
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.market.connectors.base import ConnectorError
from app.market.connectors.mt5 import MT5Connector
from app.market.service import (
    SyncStats,
    get_or_create_source,
    mark_source_error,
    sync_source,
    sync_symbols,
)
from app.models.enums import DataSourceKind, Timeframe
from app.services.seed import MT5_SOURCE

logger = logging.getLogger("traderai.mt5_bridge")

MAX_BACKOFF_SECONDS = 300


def build_connector(library: Any | None = None) -> MT5Connector:
    settings = get_settings()
    return MT5Connector(
        server_timezone=settings.mt5_server_timezone,
        terminal_path=settings.mt5_terminal_path,
        login=settings.mt5_login,
        password=settings.mt5_password,
        server=settings.mt5_server,
        library=library,
    )


def sync_once(
    db: Session,
    connector: MT5Connector,
    timeframes: list[Timeframe],
    now: datetime | None = None,
) -> SyncStats:
    """Descobre símbolos e sincroniza os monitorados. Exige conector já conectado."""
    now = now or datetime.now(UTC)
    source = get_or_create_source(db, MT5_SOURCE, DataSourceKind.MT5)
    created, _ = sync_symbols(db, source, connector.discover_symbols())
    db.commit()
    stats = sync_source(db, connector, source, now, timeframes=timeframes)
    logger.info(
        "mt5_sync",
        extra={
            "new_symbols": created,
            "series": stats.series,
            "candles": stats.candles,
            "rejected": stats.rejected,
            "errors": stats.errors[:3],
        },
    )
    return stats


def record_failure(message: str) -> None:
    with get_sessionmaker()() as db:
        source = get_or_create_source(db, MT5_SOURCE, DataSourceKind.MT5)
        mark_source_error(db, source, message)
        db.commit()


def run(timeframes: list[Timeframe], interval: float | None) -> int:
    """Laço principal. Em falha, registra o erro, fecha o terminal e reconecta com backoff."""
    backoff = 5.0
    while True:
        connector: MT5Connector | None = None
        try:
            connector = build_connector()
            connector.connect()
            backoff = 5.0
            while True:
                with get_sessionmaker()() as db:
                    sync_once(db, connector, timeframes)
                if interval is None:
                    return 0
                time.sleep(interval)
                if not connector.is_alive():
                    raise ConnectorError("Terminal MT5 desconectado do servidor da corretora.")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 — a ponte deve se recuperar de qualquer falha
            logger.exception("mt5_bridge_failure")
            try:
                record_failure(str(exc))
            except Exception:
                logger.exception("mt5_failure_not_recorded")
            if interval is None:
                return 1
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        finally:
            if connector is not None:
                connector.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ponte MT5 somente leitura do TraderAI Pro")
    parser.add_argument("--once", action="store_true", help="sincroniza uma vez e encerra")
    parser.add_argument("--interval", type=float, default=30.0, help="segundos entre ciclos")
    parser.add_argument(
        "--timeframes",
        default=",".join(t.value for t in Timeframe),
        help="lista separada por vírgulas (padrão: todos)",
    )
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    timeframes = [Timeframe(t.strip().upper()) for t in args.timeframes.split(",") if t.strip()]
    return run(timeframes, None if args.once else args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
