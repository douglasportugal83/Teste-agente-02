import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, require_permission
from app.api.routes.health import build_system_info
from app.models import (
    Alert,
    DataSource,
    RiskRule,
    SimulatedPosition,
    SimulationAccount,
    Symbol,
    User,
)
from app.models.enums import AssetCategory, PositionStatus
from app.schemas.core import (
    AlertOut,
    CategorySummary,
    ConnectionStatus,
    DashboardOverview,
    DataSourceOut,
    EquityPoint,
    RiskRuleOut,
    SimulationAccountOut,
    SimulatorSummary,
    SymbolOut,
)

router = APIRouter(prefix="/api/v1", tags=["painel"])

DashboardUser = Annotated[User, Depends(require_permission("dashboard:read"))]
MarketUser = Annotated[User, Depends(require_permission("market:read"))]


def _simulator_summary(db: Session, account: SimulationAccount) -> SimulatorSummary:
    counts = dict(
        db.execute(
            select(SimulatedPosition.status, func.count())
            .where(SimulatedPosition.account_id == account.id)
            .group_by(SimulatedPosition.status)
        ).all()
    )
    initial, equity = float(account.initial_balance), float(account.equity)
    pnl = equity - initial
    return SimulatorSummary(
        account_id=account.id,
        name=account.name,
        status=account.status,
        status_reason=account.status_reason,
        currency=account.currency,
        initial_balance=initial,
        balance=float(account.balance),
        equity=equity,
        pnl=pnl,
        pnl_pct=(pnl / initial * 100) if initial else 0.0,
        open_positions=counts.get(PositionStatus.OPEN, 0),
        closed_trades=counts.get(PositionStatus.CLOSED, 0),
    )


def _equity_curve(db: Session, account: SimulationAccount) -> list[EquityPoint]:
    """Patrimônio fictício acumulado a partir das posições simuladas encerradas."""
    points = [EquityPoint(ts=account.created_at, equity=float(account.initial_balance))]
    closed = db.execute(
        select(SimulatedPosition.closed_at, SimulatedPosition.realized_pnl)
        .where(
            SimulatedPosition.account_id == account.id,
            SimulatedPosition.status == PositionStatus.CLOSED,
            SimulatedPosition.closed_at.is_not(None),
        )
        .order_by(SimulatedPosition.closed_at)
    ).all()
    equity = float(account.initial_balance)
    for closed_at, pnl in closed:
        equity += float(pnl or 0)
        points.append(EquityPoint(ts=closed_at, equity=equity))
    return points


@router.get("/dashboard/overview", response_model=DashboardOverview)
def overview(db: DbSession, user: DashboardUser) -> DashboardOverview:
    connections = [ConnectionStatus(name="Banco de dados", kind="database", status="connected")]
    for source in db.scalars(select(DataSource).order_by(DataSource.name)):
        connections.append(
            ConnectionStatus(
                name=source.name,
                kind=source.kind,
                status=source.status,
                detail=source.last_error or source.config.get("note"),
            )
        )

    by_category: dict[AssetCategory, list[str]] = defaultdict(list)
    for name, category in db.execute(
        select(Symbol.canonical_name, Symbol.category)
        .where(Symbol.is_monitored)
        .distinct()
        .order_by(Symbol.canonical_name)
    ):
        by_category[category].append(name)
    market = [
        CategorySummary(category=c, count=len(by_category[c]), symbols=by_category[c])
        for c in AssetCategory
        if by_category.get(c)
    ]

    account = db.scalar(
        select(SimulationAccount)
        .where(SimulationAccount.user_id == user.id)
        .order_by(SimulationAccount.created_at)
        .limit(1)
    )
    alerts = db.scalars(
        select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc()).limit(5)
    ).all()
    unread = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.user_id == user.id, ~Alert.is_read)
    )

    return DashboardOverview(
        system=build_system_info(),
        connections=connections,
        monitored_symbols=sum(c.count for c in market),
        market_by_category=market,
        simulator=_simulator_summary(db, account) if account else None,
        recent_alerts=[AlertOut.model_validate(a) for a in alerts],
        unread_alerts=unread or 0,
        equity_curve=_equity_curve(db, account) if account else [],
    )


@router.get("/symbols", response_model=list[SymbolOut], tags=["mercado"])
def list_symbols(
    db: DbSession, _: MarketUser, category: AssetCategory | None = None
) -> list[Symbol]:
    query = select(Symbol).order_by(Symbol.category, Symbol.canonical_name)
    if category is not None:
        query = query.where(Symbol.category == category)
    return list(db.scalars(query))


@router.get("/data-sources", response_model=list[DataSourceOut], tags=["mercado"])
def list_data_sources(db: DbSession, _: MarketUser) -> list[DataSource]:
    return list(db.scalars(select(DataSource).order_by(DataSource.name)))


@router.get("/alerts", response_model=list[AlertOut], tags=["alertas"])
def list_alerts(
    db: DbSession,
    user: DashboardUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    unread_only: bool = False,
) -> list[Alert]:
    query = select(Alert).where(Alert.user_id == user.id)
    if unread_only:
        query = query.where(~Alert.is_read)
    return list(db.scalars(query.order_by(Alert.created_at.desc()).limit(limit)))


@router.post("/alerts/{alert_id}/read", response_model=AlertOut, tags=["alertas"])
def mark_alert_read(alert_id: uuid.UUID, db: DbSession, user: DashboardUser) -> Alert:
    # Filtrar por user_id garante o isolamento: alertas de terceiros retornam 404.
    alert = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta não encontrado.")
    alert.is_read = True
    db.commit()
    return alert


@router.get("/simulation/accounts", response_model=list[SimulationAccountOut], tags=["simulador"])
def list_simulation_accounts(db: DbSession, user: DashboardUser) -> list[SimulationAccount]:
    return list(
        db.scalars(
            select(SimulationAccount)
            .where(SimulationAccount.user_id == user.id)
            .order_by(SimulationAccount.created_at)
        )
    )


@router.get("/risk/rules", response_model=list[RiskRuleOut], tags=["risco"])
def list_risk_rules(db: DbSession, user: DashboardUser) -> list[RiskRule]:
    return list(
        db.scalars(select(RiskRule).where(RiskRule.user_id == user.id).order_by(RiskRule.rule_type))
    )
