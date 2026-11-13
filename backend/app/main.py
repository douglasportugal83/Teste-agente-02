"""Aplicação FastAPI do TraderAI Pro."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.routes import admin, auth, dashboard, health, ws
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.schemas.core import DISCLAIMER
from app.services.seed import seed_reference_data

logger = logging.getLogger("traderai.app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_runtime()
    try:
        with get_sessionmaker()() as db:
            seed_reference_data(db)
    except SQLAlchemyError:
        # A API sobe mesmo sem banco (o /health/ready sinaliza); rode `alembic upgrade head`.
        logger.exception("seed_failed")
    logger.info(
        "startup", extra={"environment": settings.environment, "mode": settings.trading_mode}
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TraderAI Pro API",
        version=__version__,
        description=(
            f"API de análise multiativos, backtesting e simulação de operações.\n\n**{DISCLAIMER}**"
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # Apenas o path é registrado: query strings e cabeçalhos podem conter segredos.
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        return response

    for module in (health, auth, dashboard, admin, ws):
        app.include_router(module.router)
    return app


app = create_app()
