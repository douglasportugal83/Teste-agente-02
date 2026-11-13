import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AssetCategory, DataSourceKind, Timeframe

SYNTHETIC_NOTICE = "Dados sintéticos gerados pelo sistema — não são cotações reais de mercado."


class CandleOut(BaseModel):
    t: int = Field(description="Abertura do candle (epoch em segundos, UTC)")
    o: float
    h: float
    low: float = Field(serialization_alias="l")
    c: float
    v: float


class CandleSeries(BaseModel):
    symbol_id: uuid.UUID
    symbol: str
    canonical_name: str
    timeframe: Timeframe
    digits: int
    source_kind: DataSourceKind
    is_synthetic: bool
    notice: str | None
    candles: list[CandleOut]


class QuoteOut(BaseModel):
    symbol_id: uuid.UUID
    name: str
    canonical_name: str
    category: AssetCategory
    digits: int
    source_kind: DataSourceKind
    is_synthetic: bool
    price: float | None
    price_ts: datetime | None
    change_pct: float | None
    is_stale: bool


class CoverageOut(BaseModel):
    symbol_id: uuid.UUID
    symbol: str
    source: str
    timeframe: Timeframe
    candles: int
    first_ts: datetime
    last_ts: datetime


class QualityIssueOut(BaseModel):
    code: str
    severity: str
    message: str
    count: int
    examples: list[datetime]


class QualityReportOut(BaseModel):
    symbol: str
    timeframe: Timeframe
    candles: int
    first_ts: datetime | None
    last_ts: datetime | None
    expected_candles: int
    completeness_pct: float
    is_stale: bool
    last_candle_age_seconds: int | None
    score: int
    issues: list[QualityIssueOut]


class BackfillRequest(BaseModel):
    symbol_ids: list[uuid.UUID] | None = Field(
        default=None, description="Vazio = todos os símbolos monitorados da fonte"
    )
    timeframes: list[Timeframe] = Field(min_length=1)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _period(self) -> "BackfillRequest":
        if self.end <= self.start:
            raise ValueError("O fim do período deve ser posterior ao início.")
        return self


class SyncReport(BaseModel):
    series: int
    candles: int
    rejected: int
    errors: list[str]


class ImportReport(BaseModel):
    symbol_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    rows_read: int
    rows_imported: int
    rows_rejected: int
    rejected_by_reason: dict[str, int]
    first_ts: datetime | None
    last_ts: datetime | None
    quality: QualityReportOut


class SymbolUpdate(BaseModel):
    is_monitored: bool
