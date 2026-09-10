"""
用户管理接口测试
admin鉴权 + 角色修改 + 启停 + 自我保护
"""
from tests.conftest import register_and_login, requires_db


def _find_user(client, headers, username):
    users = client.get("/api/users", headers=headers).json()
    return next(u for u in users if u["username"] == username)


@requires_db
def test_list_requires_admin(client):
    resp = client.get("/api/users", headers=register_and_login(client, "us_e1"))
    assert resp.status_code == 403


@requires_db
def test_admin_cannot_modify_self(client):
    """自我保护：改自己角色/状态都返回400"""
    headers = register_and_login(client, "us_admin1", role="admin")
    me = _find_user(client, headers, "us_admin1")
    resp = client.patch(
        f"/api/users/{me['id']}/role", json={"role": "employee"}, headers=headers
    )
    assert resp.status_code == 400
    resp = client.patch(
        f"/api/users/{me['id']}/status", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 400


@requires_db
def test_admin_can_modify_other(client):
    headers = register_and_login(client, "us_admin2", role="admin")
    register_and_login(client, "us_emp2")
    other = _find_user(client, headers, "us_emp2")

    resp = client.patch(
        f"/api/users/{other['id']}/role", json={"role": "manager"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"

    resp = client.patch(
        f"/api/users/{other['id']}/status", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@requires_db
def test_get_404(client):
    headers = register_and_login(client, "us_admin3", role="admin")
    resp = client.get("/api/users/99999", headers=headers)
    assert resp.status_code == 404
