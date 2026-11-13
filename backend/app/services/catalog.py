"""Catálogo inicial de ativos e papéis. Símbolos reais são descobertos na fonte (Sprint 2)."""

from app.models.enums import AssetCategory, RiskRuleType

M, IDX, C, F = (
    AssetCategory.METALS,
    AssetCategory.INDICES,
    AssetCategory.CRYPTO,
    AssetCategory.FOREX,
)

# (nome canônico, descrição, categoria, base, cotação, casas decimais)
DEFAULT_SYMBOLS: list[tuple[str, str, AssetCategory, str | None, str, int]] = [
    ("XAUUSD", "Ouro vs Dólar", M, "XAU", "USD", 2),
    ("XAGUSD", "Prata vs Dólar", M, "XAG", "USD", 3),
    ("NAS100", "Nasdaq 100 (USTEC)", IDX, None, "USD", 1),
    ("US30", "Dow Jones 30", IDX, None, "USD", 1),
    ("US500", "S&P 500", IDX, None, "USD", 1),
    ("GER40", "DAX 40", IDX, None, "EUR", 1),
    ("BTCUSD", "Bitcoin vs Dólar", C, "BTC", "USD", 2),
    ("ETHUSD", "Ethereum vs Dólar", C, "ETH", "USD", 2),
    ("EURUSD", "Euro vs Dólar", F, "EUR", "USD", 5),
    ("GBPUSD", "Libra vs Dólar", F, "GBP", "USD", 5),
    ("USDJPY", "Dólar vs Iene", F, "USD", "JPY", 3),
    ("USDCAD", "Dólar vs Dólar Canadense", F, "USD", "CAD", 5),
    ("AUDUSD", "Dólar Australiano vs Dólar", F, "AUD", "USD", 5),
]

# Nomes alternativos usados por corretoras -> nome canônico.
SYMBOL_ALIASES: dict[str, str] = {
    "USTEC": "NAS100",
    "US100": "NAS100",
    "NDX100": "NAS100",
    "DJ30": "US30",
    "SPX500": "US500",
    "DE40": "GER40",
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD",
}

PERMISSIONS = [
    "dashboard:read",
    "market:read",
    "strategies:read",
    "strategies:write",
    "backtests:run",
    "simulator:control",
    "risk:write",
    "ai:use",
    "admin:users",
    "admin:audit",
    "admin:data_sources",
]

ROLE_ADMIN, ROLE_TRADER, ROLE_VIEWER = "admin", "trader", "viewer"

DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    ROLE_ADMIN: ("Acesso total, incluindo administração.", PERMISSIONS),
    ROLE_TRADER: (
        "Opera o simulador, estratégias e backtests próprios.",
        [p for p in PERMISSIONS if not p.startswith("admin:")],
    ),
    ROLE_VIEWER: (
        "Somente leitura.",
        ["dashboard:read", "market:read", "strategies:read"],
    ),
}

# (tipo, valor padrão, descrição)
DEFAULT_RISK_RULES: list[tuple[RiskRuleType, float, str]] = [
    (RiskRuleType.MAX_DAILY_LOSS, 2000.0, "Perda diária fictícia máxima (moeda da conta)."),
    (RiskRuleType.MAX_EXPOSURE_PER_SYMBOL, 20.0, "Exposição máxima por ativo (% do patrimônio)."),
    (RiskRuleType.MAX_OPEN_POSITIONS, 5.0, "Máximo de posições simuladas simultâneas."),
    (RiskRuleType.MAX_CORRELATED_POSITIONS, 2.0, "Máximo de posições em ativos correlacionados."),
    (RiskRuleType.RISK_PER_TRADE_PCT, 1.0, "Risco por operação (% do patrimônio)."),
    (RiskRuleType.MAX_DRAWDOWN_PCT, 10.0, "Drawdown máximo antes do bloqueio (%)."),
    (RiskRuleType.MAX_VOLATILITY_ATR_PCT, 5.0, "Volatilidade máxima (ATR % do preço)."),
]
