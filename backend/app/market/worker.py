"""Atualizador em segundo plano da fonte sintética.

Mantém as séries dos símbolos monitorados em dia, acrescentando os candles que fecharam desde
a última execução. Roda numa thread dentro da API (MARKET_WORKER_ENABLED) — as gravações são
idempotentes, então mais de uma instância não corrompe dados, apenas repete trabalho.
"""

import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.market.connectors.synthetic import SyntheticConnector
from app.market.service import SyncStats, mark_source_error, sync_source, sync_symbols
from app.models import DataSource
from app.models.enums import DataSourceKind

logger = logging.getLogger("traderai.market.worker")


def sync_synthetic_sources(db: Session, now: datetime | None = None) -> SyncStats:
    """Uma passada de sincronização em todas as fontes sintéticas habilitadas."""
    now = now or datetime.now(UTC)
    connector = SyntheticConnector(now=lambda: now)
    total = SyncStats()
    sources = db.scalars(
        select(DataSource).where(DataSource.kind == DataSourceKind.SYNTHETIC, DataSource.is_enabled)
    ).all()
    for source in sources:
        sync_symbols(db, source, connector.discover_symbols())
        stats = sync_source(db, connector, source, now)
        total.series += stats.series
        total.candles += stats.candles
        total.rejected += stats.rejected
        total.errors += stats.errors
    return total


class MarketWorker:
    def __init__(self, session_factory: sessionmaker[Session], interval_seconds: float) -> None:
        self._session_factory = session_factory
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> None:
        try:
            with self._session_factory() as db:
                stats = sync_synthetic_sources(db)
            if stats.candles or stats.errors:
                logger.info(
                    "market_sync",
                    extra={
                        "series": stats.series,
                        "candles": stats.candles,
                        "rejected": stats.rejected,
                        "errors": stats.errors[:3],
                    },
                )
        except Exception as exc:  # a thread precisa sobreviver a qualquer falha (ex.: banco fora)
            logger.exception("market_sync_failed")
            self._record_failure(str(exc))

    def _record_failure(self, message: str) -> None:
        try:
            with self._session_factory() as db:
                for source in db.scalars(
                    select(DataSource).where(DataSource.kind == DataSourceKind.SYNTHETIC)
                ):
                    mark_source_error(db, source, message)
                db.commit()
        except Exception:
            logger.exception("market_sync_failure_not_recorded")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="market-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
