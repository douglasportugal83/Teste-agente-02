import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from tests.conftest import PASSWORD, login, register


def test_register_first_user_is_admin_then_trader(client: TestClient) -> None:
    first = register(client, "Primeiro@Example.com")
    second = register(client, "segundo@example.com")
    assert first["email"] == "primeiro@example.com"
    assert first["role"]["name"] == "admin"
    assert second["role"]["name"] == "trader"
    assert "hashed_password" not in first and "password" not in first


def test_register_duplicate_email(client: TestClient) -> None:
    register(client, "dup@example.com")
    response = client.post(
        "/api/v1/auth/register", json={"email": "DUP@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409


@pytest.mark.parametrize("password", ["curta1!", "12345678", "somenteletras"])
def test_register_rejects_weak_password(client: TestClient, password: str) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": password}
    )
    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "nao-e-email", "password": PASSWORD}
    )
    assert response.status_code == 422


def test_password_is_stored_hashed(client: TestClient, db: Session) -> None:
    register(client, "hash@example.com")
    user = db.scalar(select(User).where(User.email == "hash@example.com"))
    assert user is not None
    assert user.hashed_password != PASSWORD and user.hashed_password.startswith("$2")


def test_login_and_me(client: TestClient) -> None:
    register(client, "me@example.com")
    headers = login(client, "ME@example.com")
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["last_login_at"] is not None


def test_oauth2_form_login(client: TestClient) -> None:
    register(client, "form@example.com")
    response = client.post(
        "/api/v1/auth/token", data={"username": "form@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200 and response.json()["token_type"] == "bearer"


def test_login_wrong_password_and_unknown_user_are_indistinguishable(client: TestClient) -> None:
    register(client, "a@example.com")
    wrong = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"})
    unknown = client.post("/api/v1/auth/login", json={"email": "z@example.com", "password": "x"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_protected_routes_require_valid_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    bad = {"Authorization": "Bearer token-invalido"}
    assert client.get("/api/v1/auth/me", headers=bad).status_code == 401
    assert client.get("/api/v1/dashboard/overview").status_code == 401


def test_login_is_rate_limited_after_repeated_failures(client: TestClient) -> None:
    register(client, "brute@example.com")
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login", json={"email": "brute@example.com", "password": "errada"}
        )
        assert response.status_code == 401
    # Mesmo com a senha correta, o bloqueio permanece até a janela expirar.
    response = client.post(
        "/api/v1/auth/login", json={"email": "brute@example.com", "password": PASSWORD}
    )
    assert response.status_code == 429


def test_inactive_user_cannot_login_or_use_token(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = register(client, "off@example.com")
    headers = login(client, "off@example.com")
    response = client.patch(
        f"/api/v1/admin/users/{created['id']}", json={"is_active": False}, headers=admin_headers
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    response = client.post(
        "/api/v1/auth/login", json={"email": "off@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_credentials_never_reach_logs_or_audit(
    client: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "Segredo-unico-98765"
    with caplog.at_level(logging.DEBUG):
        register(client, "log@example.com", secret)
        headers = login(client, "log@example.com", secret)
        client.post("/api/v1/auth/login", json={"email": "log@example.com", "password": "errada!"})
        client.get("/api/v1/auth/me", headers=headers)
    token = headers["Authorization"].split()[1]
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert secret not in logged and "errada!" not in logged and token not in logged

    actions = [(a.action, str(a.details)) for a in db.scalars(select(AuditLog))]
    assert {a for a, _ in actions} >= {"user.registered", "auth.login", "auth.login_failed"}
    assert all(secret not in d and "errada!" not in d for _, d in actions)
