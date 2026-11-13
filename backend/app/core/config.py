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

    default_simulation_balance: float = 100_000.0
    default_simulation_currency: str = "USD"

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
