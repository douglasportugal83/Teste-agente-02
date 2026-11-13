import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    AlertSeverity,
    AssetCategory,
    DataSourceKind,
    DataSourceStatus,
    RiskRuleType,
    SimulationStatus,
)

DISCLAIMER = (
    "Ambiente exclusivamente de simulação: nenhuma ordem real é enviada. "
    "Resultados simulados ou históricos não garantem resultados futuros."
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DataSourceOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: DataSourceKind
    status: DataSourceStatus
    read_only: bool
    is_enabled: bool
    last_sync_at: datetime | None
    last_error: str | None


class SymbolOut(ORMModel):
    id: uuid.UUID
    name: str
    canonical_name: str
    description: str | None
    category: AssetCategory
    base_currency: str | None
    quote_currency: str | None
    digits: int
    is_monitored: bool
    data_source_id: uuid.UUID


class AlertOut(ORMModel):
    id: uuid.UUID
    severity: AlertSeverity
    category: str
    title: str
    message: str
    is_read: bool
    created_at: datetime


class SimulationAccountOut(ORMModel):
    id: uuid.UUID
    name: str
    currency: str
    initial_balance: float
    balance: float
    equity: float
    status: SimulationStatus
    status_reason: str | None
    is_virtual: bool
    created_at: datetime


class RiskRuleOut(ORMModel):
    id: uuid.UUID
    account_id: uuid.UUID
    rule_type: RiskRuleType
    value: float
    is_enabled: bool
    description: str | None


class AuditLogOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]
    ip_address: str | None
    created_at: datetime


class SystemInfo(BaseModel):
    app_name: str
    version: str
    environment: str
    trading_mode: str
    real_orders_enabled: bool
    server_time: datetime
    disclaimer: str = DISCLAIMER


class ConnectionStatus(BaseModel):
    name: str
    kind: str
    status: str
    detail: str | None = None


class CategorySummary(BaseModel):
    category: AssetCategory
    count: int
    symbols: list[str]


class SimulatorSummary(BaseModel):
    account_id: uuid.UUID
    name: str
    status: SimulationStatus
    status_reason: str | None
    currency: str
    initial_balance: float
    balance: float
    equity: float
    pnl: float
    pnl_pct: float
    open_positions: int
    closed_trades: int


class EquityPoint(BaseModel):
    ts: datetime
    equity: float


class DashboardOverview(BaseModel):
    system: SystemInfo
    connections: list[ConnectionStatus]
    monitored_symbols: int
    market_by_category: list[CategorySummary]
    simulator: SimulatorSummary | None
    recent_alerts: list[AlertOut]
    unread_alerts: int
    equity_curve: list[EquityPoint]
