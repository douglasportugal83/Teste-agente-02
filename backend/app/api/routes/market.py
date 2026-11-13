"""Dados de mercado: consulta de candles, cotações, qualidade, importação e sincronização."""

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import DbSession, client_ip, require_permission
from app.core.config import get_settings
from app.market import service
from app.market.candles import CandleBatch
from app.market.connectors.file_import import ImportFormatError, parse_candle_file
from app.market.connectors.synthetic import SyntheticConnector
from app.market.quality import QualityReport, assess_quality
from app.market.symbols import canonical_name, currencies, infer_category
from app.market.timeframes import TIMEFRAME_SECONDS, from_epoch
from app.market.worker import sync_synthetic_sources
from app.models import DataSource, Symbol, User
from app.models.enums import AssetCategory, DataSourceKind, Timeframe
from app.schemas.core import SymbolOut
from app.schemas.market import (
    SYNTHETIC_NOTICE,
    BackfillRequest,
    CandleOut,
    CandleSeries,
    CoverageOut,
    ImportReport,
    QualityReportOut,
    QuoteOut,
    SymbolUpdate,
    SyncReport,
)
from app.services import audit

router = APIRouter(prefix="/api/v1", tags=["mercado"])

MarketUser = Annotated[User, Depends(require_permission("market:read"))]
SourcesAdmin = Annotated[User, Depends(require_permission("admin:data_sources"))]

IMPORT_SOURCES = {
    DataSourceKind.CSV: "Arquivos importados (CSV)",
    DataSourceKind.PARQUET: "Arquivos importados (Parquet)",
}
QUALITY_MAX_CANDLES = 200_000


def _symbol_or_404(db: DbSession, symbol_id: uuid.UUID) -> Symbol:
    symbol = db.get(Symbol, symbol_id)
    if symbol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Símbolo não encontrado.")
    return symbol


def _quality_out(symbol: Symbol, timeframe: Timeframe, report: QualityReport) -> QualityReportOut:
    return QualityReportOut(symbol=symbol.name, timeframe=timeframe, **asdict(report))


def _assess(symbol: Symbol, timeframe: Timeframe, batch: CandleBatch) -> QualityReportOut:
    report = assess_quality(
        batch,
        timeframe,
        always_open=symbol.category is AssetCategory.CRYPTO,
        now=datetime.now(UTC),
    )
    return _quality_out(symbol, timeframe, report)


@router.get("/market/candles", response_model=CandleSeries)
def get_candles(
    db: DbSession,
    _: MarketUser,
    symbol_id: uuid.UUID,
    timeframe: Timeframe = Timeframe.H1,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> CandleSeries:
    """Candles fechados em ordem cronológica (os `limit` mais recentes do intervalo)."""
    symbol = _symbol_or_404(db, symbol_id)
    batch = service.load_candles(db, symbol.id, timeframe, start=start, end=end, limit=limit)
    synthetic = symbol.data_source.kind is DataSourceKind.SYNTHETIC
    return CandleSeries(
        symbol_id=symbol.id,
        symbol=symbol.name,
        canonical_name=symbol.canonical_name,
        timeframe=timeframe,
        digits=symbol.digits,
        source_kind=symbol.data_source.kind,
        is_synthetic=synthetic,
        notice=SYNTHETIC_NOTICE if synthetic else None,
        candles=[
            CandleOut(
                t=int(batch.ts[i]),
                o=float(batch.open[i]),
                h=float(batch.high[i]),
                low=float(batch.low[i]),
                c=float(batch.close[i]),
                v=float(batch.volume[i]),
            )
            for i in range(len(batch))
        ],
    )


@router.get("/market/quotes", response_model=list[QuoteOut])
def get_quotes(db: DbSession, _: MarketUser) -> list[QuoteOut]:
    return [
        QuoteOut(**asdict(q), is_synthetic=q.source_kind is DataSourceKind.SYNTHETIC)
        for q in service.quotes(db, datetime.now(UTC))
    ]


@router.get("/market/quality", response_model=QualityReportOut)
def get_quality(
    db: DbSession, _: MarketUser, symbol_id: uuid.UUID, timeframe: Timeframe = Timeframe.H1
) -> QualityReportOut:
    """Avaliação de qualidade da série armazenada (lacunas, anomalias, atraso)."""
    symbol = _symbol_or_404(db, symbol_id)
    batch = service.load_candles(db, symbol.id, timeframe, limit=QUALITY_MAX_CANDLES)
    return _assess(symbol, timeframe, batch)


@router.get("/market/coverage", response_model=list[CoverageOut])
def get_coverage(db: DbSession, _: MarketUser) -> list[CoverageOut]:
    """Quantidade e período dos candles armazenados por símbolo e timeframe."""
    symbols = {
        s.id: (s.name, source_name)
        for s, source_name in db.execute(select(Symbol, DataSource.name).join(DataSource))
    }
    order = {t: i for i, t in enumerate(Timeframe)}
    rows = [
        CoverageOut(
            symbol_id=c.symbol_id,
            symbol=symbols[c.symbol_id][0],
            source=symbols[c.symbol_id][1],
            timeframe=c.timeframe,
            candles=c.candles,
            first_ts=c.first_ts,
            last_ts=c.last_ts,
        )
        for c in service.coverage(db)
        if c.symbol_id in symbols
    ]
    return sorted(rows, key=lambda r: (r.source, r.symbol, order[r.timeframe]))


# --- Administração de fontes de dados -------------------------------------------------


def _synthetic_source_or_error(db: DbSession, source_id: uuid.UUID) -> DataSource:
    source = db.get(DataSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonte de dados não encontrada.")
    if source.kind is not DataSourceKind.SYNTHETIC:
        detail = (
            "A fonte MT5 é sincronizada pela ponte (python -m app.market.mt5_bridge), "
            "que roda junto ao terminal."
            if source.kind is DataSourceKind.MT5
            else "Fontes de arquivo são alimentadas pela importação."
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
    return source


@router.post("/admin/data-sources/{source_id}/sync", response_model=SyncReport)
def sync_data_source(
    source_id: uuid.UUID, request: Request, db: DbSession, admin: SourcesAdmin
) -> SyncReport:
    """Descobre símbolos e traz os candles que faltam (fonte sintética)."""
    source = _synthetic_source_or_error(db, source_id)
    stats = sync_synthetic_sources(db)
    audit.record(
        db,
        "market.sync",
        user_id=admin.id,
        entity_type="data_source",
        entity_id=source.id,
        details={"series": stats.series, "candles": stats.candles},
        ip_address=client_ip(request),
    )
    db.commit()
    return SyncReport(**asdict(stats))


@router.post("/admin/data-sources/{source_id}/backfill", response_model=SyncReport)
def backfill_data_source(
    source_id: uuid.UUID,
    payload: BackfillRequest,
    request: Request,
    db: DbSession,
    admin: SourcesAdmin,
) -> SyncReport:
    """Gera (ou regera) um período histórico explícito na fonte sintética."""
    source = _synthetic_source_or_error(db, source_id)
    query = select(Symbol).where(Symbol.data_source_id == source.id)
    if payload.symbol_ids:
        query = query.where(Symbol.id.in_(payload.symbol_ids))
    else:
        query = query.where(Symbol.is_monitored)
    symbols = db.scalars(query).all()
    if not symbols:
        raise HTTPException(422, "Nenhum símbolo desta fonte corresponde ao pedido.")

    seconds = (payload.end - payload.start).total_seconds()
    estimate = sum(seconds / TIMEFRAME_SECONDS[t] for t in payload.timeframes) * len(symbols)
    maximum = get_settings().backfill_max_candles
    if estimate > maximum:
        raise HTTPException(
            422,
            f"Pedido estimado em {estimate:,.0f} candles; o limite por requisição é {maximum:,}. "
            "Reduza o período, os timeframes ou os símbolos.",
        )

    now = datetime.now(UTC)
    stats = service.backfill(
        db,
        SyntheticConnector(now=lambda: now),
        symbols,
        payload.timeframes,
        payload.start,
        payload.end,
        now,
    )
    service.mark_source_ok(db, source, now)
    audit.record(
        db,
        "market.backfill",
        user_id=admin.id,
        entity_type="data_source",
        entity_id=source.id,
        details={
            "symbols": len(symbols),
            "timeframes": [t.value for t in payload.timeframes],
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "candles": stats.candles,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    return SyncReport(**asdict(stats))


@router.post("/admin/market/import", response_model=ImportReport)
def import_candles(
    request: Request,
    db: DbSession,
    admin: SourcesAdmin,
    file: Annotated[UploadFile, File(description="Arquivo .csv ou .parquet")],
    symbol: Annotated[str, Form(min_length=1, max_length=40)],
    timeframe: Annotated[Timeframe, Form()],
    source_timezone: Annotated[
        str, Form(description="Fuso dos horários do arquivo (IANA), ex.: UTC, Europe/Athens")
    ] = "UTC",
    category: Annotated[AssetCategory | None, Form()] = None,
) -> ImportReport:
    """Importa histórico de um arquivo. Linhas inválidas são rejeitadas e contabilizadas;
    reimportar o mesmo arquivo não duplica candles."""
    filename = file.filename or ""
    kind = (
        DataSourceKind.PARQUET
        if filename.lower().endswith((".parquet", ".pq"))
        else DataSourceKind.CSV
    )
    maximum = get_settings().import_max_bytes
    content = file.file.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Arquivo maior que o limite de {maximum // (1024 * 1024)} MB.",
        )
    try:
        batch = parse_candle_file(content, filename, source_timezone)
    except ImportFormatError as exc:
        raise HTTPException(422, str(exc)) from exc

    source = service.get_or_create_source(db, IMPORT_SOURCES[kind], kind)
    name = symbol.strip().upper()
    record = db.scalar(
        select(Symbol).where(Symbol.data_source_id == source.id, Symbol.name == name)
    )
    if record is None:
        canonical = canonical_name(name)
        base, quote = currencies(canonical)
        record = Symbol(
            data_source_id=source.id,
            name=name,
            canonical_name=canonical,
            category=category or infer_category(canonical),
            base_currency=base,
            quote_currency=quote,
            digits=_infer_digits(batch),
            is_monitored=True,
        )
        db.add(record)
        db.flush()

    now = datetime.now(UTC)
    result = service.ingest(db, record, timeframe, batch, now)
    service.mark_source_ok(db, source, now)
    audit.record(
        db,
        "market.import",
        user_id=admin.id,
        entity_type="symbol",
        entity_id=record.id,
        details={
            "file": filename,
            "timeframe": timeframe.value,
            "rows_read": result.rows_read,
            "rows_imported": len(result.batch),
            "rejected": result.rejected,
        },
        ip_address=client_ip(request),
    )
    db.commit()

    stored = service.load_candles(db, record.id, timeframe, limit=QUALITY_MAX_CANDLES)
    imported = result.batch
    return ImportReport(
        symbol_id=record.id,
        symbol=record.name,
        timeframe=timeframe,
        rows_read=result.rows_read,
        rows_imported=len(imported),
        rows_rejected=result.rows_rejected,
        rejected_by_reason=result.rejected,
        first_ts=from_epoch(int(imported.ts[0])) if len(imported) else None,
        last_ts=from_epoch(int(imported.ts[-1])) if len(imported) else None,
        quality=_assess(record, timeframe, stored),
    )


def _infer_digits(batch: CandleBatch) -> int:
    """Casas decimais observadas nos preços de fechamento (amostra)."""
    digits = 0
    for value in batch.close[:200].tolist():
        text = f"{value:.8f}".rstrip("0")
        if "." in text:
            digits = max(digits, len(text.split(".")[1]))
    return min(digits, 8)


@router.patch("/admin/symbols/{symbol_id}", response_model=SymbolOut)
def update_symbol(
    symbol_id: uuid.UUID,
    payload: SymbolUpdate,
    request: Request,
    db: DbSession,
    admin: SourcesAdmin,
) -> Symbol:
    """Inclui ou retira um símbolo do monitoramento."""
    symbol = _symbol_or_404(db, symbol_id)
    if symbol.is_monitored != payload.is_monitored:
        symbol.is_monitored = payload.is_monitored
        audit.record(
            db,
            "market.symbol_updated",
            user_id=admin.id,
            entity_type="symbol",
            entity_id=symbol.id,
            details={"is_monitored": payload.is_monitored},
            ip_address=client_ip(request),
        )
        db.commit()
    return symbol
