"""Fixtures: banco isolado por teste (SQLite em memória ou PostgreSQL via TEST_DATABASE_URL)."""

import os
from collections.abc import Iterator

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MARKET_WORKER_ENABLED", "false")
os.environ.setdefault("TERMINAL_ENGINE_ENABLED", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-with-at-least-32-characters!!")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.auth import login_limiter
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.services.seed import seed_reference_data

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
PASSWORD = "Senha-forte-123"


@pytest.fixture
def engine() -> Iterator[Engine]:
    if TEST_DATABASE_URL.startswith("sqlite"):
        eng = create_engine(
            TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    else:
        eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        seed_reference_data(session)
        yield session


@pytest.fixture
def client(
    db: Session, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    # O lifespan e o WebSocket abrem sessões próprias: apontá-los para o banco de teste.
    monkeypatch.setattr("app.main.get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("app.api.routes.ws.get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("app.api.routes.terminal.get_sessionmaker", lambda: session_factory)
    login_limiter.reset()
    app = create_app()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Usuário Teste"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    register(client, "admin@example.com")
    return login(client, "admin@example.com")


@pytest.fixture
def trader_headers(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    register(client, "trader@example.com")
    return login(client, "trader@example.com")
