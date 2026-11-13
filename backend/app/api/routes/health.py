import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import DbSession
from app.core.config import get_settings
from app.schemas.core import SystemInfo

router = APIRouter(tags=["sistema"])
logger = logging.getLogger("traderai.health")


@router.get("/health", summary="Liveness")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness (verifica o banco de dados)")
def ready(db: DbSession, response: Response) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("database_unavailable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "error"}
    return {"status": "ok", "database": "ok"}


def build_system_info() -> SystemInfo:
    settings = get_settings()
    return SystemInfo(
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        trading_mode=settings.trading_mode,
        real_orders_enabled=False,  # constante: não há caminho de execução real no sistema
        server_time=datetime.now(UTC),
    )


@router.get("/api/v1/system/info", response_model=SystemInfo, summary="Informações do sistema")
def system_info() -> SystemInfo:
    return build_system_info()
