"""Enumerações de domínio (persistidas como texto com CHECK constraint)."""

from enum import StrEnum


class AssetCategory(StrEnum):
    METALS = "metals"
    INDICES = "indices"
    CRYPTO = "crypto"
    FOREX = "forex"
    OTHER = "other"


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"


class DataSourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    CSV = "csv"
    PARQUET = "parquet"
    MT5 = "mt5"


class DataSourceStatus(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"


class StrategyFamily(StrEnum):
    SMC = "smc"
    ICT = "ict"
    WYCKOFF = "wyckoff"
    TREND_FOLLOWING = "trend_following"
    PRICE_ACTION = "price_action"
    QUANT_INDICATORS = "quant_indicators"
    CUSTOM = "custom"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SimulationStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"  # bloqueio automático pelo módulo de risco
    STOPPED = "stopped"  # interrupção imediata pelo usuário


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class RiskRuleType(StrEnum):
    MAX_DAILY_LOSS = "max_daily_loss"
    MAX_EXPOSURE_PER_SYMBOL = "max_exposure_per_symbol"
    MAX_OPEN_POSITIONS = "max_open_positions"
    MAX_CORRELATED_POSITIONS = "max_correlated_positions"
    RISK_PER_TRADE_PCT = "risk_per_trade_pct"
    MAX_DRAWDOWN_PCT = "max_drawdown_pct"
    MAX_VOLATILITY_ATR_PCT = "max_volatility_atr_pct"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
