"""Configuração central carregada de variáveis de ambiente."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {"", "change-me", "changeme", "secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "TraderAI Pro"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://traderai:traderai@localhost:5432/traderai"

    jwt_secret: str = Field(default="change-me", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    cors_origins: str = "http://localhost:3000"

    # O sistema opera exclusivamente em simulação. Não existe outro valor aceito:
    # qualquer tentativa de configurar outro modo impede a aplicação de iniciar.
    trading_mode: Literal["simulation"] = "simulation"

    allow_registration: bool = True
    login_max_failures: int = 5
    login_failure_window_seconds: int = 900

    # --- Dados de mercado ---
    # Atualizador em segundo plano dos candles sintéticos (dentro do processo da API).
    market_worker_enabled: bool = True
    market_worker_interval_seconds: int = 20
    import_max_bytes: int = 50 * 1024 * 1024
    backfill_max_candles: int = 600_000

    # --- Ponte MT5 (usadas somente por `python -m app.market.mt5_bridge`) ---
    mt5_terminal_path: str | None = None
    mt5_login: int | None = None
    mt5_password: str | None = Field(default=None, repr=False)  # senha de INVESTIDOR
    mt5_server: str | None = None
    # Fuso do servidor da corretora (IANA). Muitas usam "Europe/Athens" (EET/EEST).
    mt5_server_timezone: str = "UTC"

    default_simulation_balance: float = 100_000.0
    default_simulation_currency: str = "USD"

    @field_validator("mt5_terminal_path", "mt5_login", "mt5_password", "mt5_server", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # Linhas "VAR=" copiadas do .env.example significam "não configurado".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        # Supabase/Heroku fornecem "postgres://" ou "postgresql://"; usamos o driver psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_runtime(self) -> None:
        """Recusa iniciar em produção com segredo inseguro."""
        if self.environment == "production" and (
            self.jwt_secret in _INSECURE_SECRETS or len(self.jwt_secret) < 32
        ):
            raise RuntimeError(
                "JWT_SECRET ausente ou fraco: defina um segredo com pelo menos 32 caracteres."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
