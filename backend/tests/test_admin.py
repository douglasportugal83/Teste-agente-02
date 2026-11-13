from fastapi.testclient import TestClient

from tests.conftest import login, register


def test_admin_endpoints_forbidden_for_trader(
    client: TestClient, trader_headers: dict[str, str]
) -> None:
    for path in ("/api/v1/admin/users", "/api/v1/admin/audit-logs", "/api/v1/admin/roles"):
        assert client.get(path, headers=trader_headers).status_code == 403
        assert client.get(path).status_code == 401


def test_admin_lists_users_roles_and_audit(
    client: TestClient, admin_headers: dict[str, str], trader_headers: dict[str, str]
) -> None:
    users = client.get("/api/v1/admin/users", headers=admin_headers).json()
    assert [u["role"]["name"] for u in users] == ["admin", "trader"]
    roles = client.get("/api/v1/admin/roles", headers=admin_headers).json()
    assert {r["name"] for r in roles} == {"admin", "trader", "viewer"}
    logs = client.get("/api/v1/admin/audit-logs", headers=admin_headers).json()
    assert {entry["action"] for entry in logs} >= {"user.registered", "auth.login"}
    only = client.get("/api/v1/admin/audit-logs?action=auth.login", headers=admin_headers).json()
    assert only and all(entry["action"] == "auth.login" for entry in only)


def test_role_change_applies_permissions_and_is_audited(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    viewer = register(client, "viewer@example.com")
    headers = login(client, "viewer@example.com")
    response = client.patch(
        f"/api/v1/admin/users/{viewer['id']}", json={"role": "viewer"}, headers=admin_headers
    )
    assert response.status_code == 200 and response.json()["role"]["name"] == "viewer"
    assert client.get("/api/v1/dashboard/overview", headers=headers).status_code == 200
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403

    logs = client.get(
        "/api/v1/admin/audit-logs?action=admin.user_updated", headers=admin_headers
    ).json()
    assert logs[0]["details"] == {"role": {"from": "trader", "to": "viewer"}}

    bad = client.patch(
        f"/api/v1/admin/users/{viewer['id']}", json={"role": "inexistente"}, headers=admin_headers
    )
    assert bad.status_code == 422


def test_last_admin_cannot_be_demoted_or_deactivated(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    for payload in ({"role": "trader"}, {"is_active": False}):
        response = client.patch(
            f"/api/v1/admin/users/{me['id']}", json=payload, headers=admin_headers
        )
        assert response.status_code == 409
