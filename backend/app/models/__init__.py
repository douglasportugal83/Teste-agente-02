"""Modelos ORM. Importar este pacote registra todas as tabelas em Base.metadata."""

from app.models.backtest import BacktestResult, BacktestRun
from app.models.market import DataSource, MarketCandle, Symbol
from app.models.monitoring import AIAnalysis, Alert, AuditLog
from app.models.simulation import RiskRule, SimulatedOrder, SimulatedPosition, SimulationAccount
from app.models.strategy import Strategy, StrategyParameter, StrategyVersion
from app.models.user import Role, User

__all__ = [
    "AIAnalysis",
    "Alert",
    "AuditLog",
    "BacktestResult",
    "BacktestRun",
    "DataSource",
    "MarketCandle",
    "RiskRule",
    "Role",
    "SimulatedOrder",
    "SimulatedPosition",
    "SimulationAccount",
    "Strategy",
    "StrategyParameter",
    "StrategyVersion",
    "Symbol",
    "User",
]
