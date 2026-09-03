"""
认证接口测试（需测试DB）
"""
from tests.conftest import register_and_login, requires_db


@requires_db
def test_register_success(client):
    """注册成功返回201与用户信息"""
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "newuser",
            "email": "new@test.com",
            "password": "pass123456",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "newuser"
    assert body["role"] == "employee"
    assert "hashed_password" not in body  # 密码哈希不得泄露


@requires_db
def test_register_duplicate_username(client):
    """重复用户名返回409"""
    client.post(
        "/api/auth/register",
        json={"username": "dup", "email": "d1@test.com", "password": "pass123456"},
    )
    resp = client.post(
        "/api/auth/register",
        json={"username": "dup", "email": "d2@test.com", "password": "pass123456"},
    )
    assert resp.status_code == 409


@requires_db
def test_login_and_me(client):
    """登录成功拿到token并访问me"""
    headers = register_and_login(client, "loginuser")
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "loginuser"


@requires_db
def test_login_wrong_password(client):
    """错误密码返回401"""
    client.post(
        "/api/auth/register",
        json={"username": "wrongpw", "email": "w@test.com", "password": "pass123456"},
    )
    resp = client.post(
        "/api/auth/login-json", json={"username": "wrongpw", "password": "badpassword"}
    )
    assert resp.status_code == 401


@requires_db
def test_me_without_token(client):
    """无token访问me返回401"""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


@requires_db
def test_users_admin_only(client):
    """用户列表仅admin可见：employee得403，admin得200"""
    employee_headers = register_and_login(client, "u_employee")
    resp = client.get("/api/users", headers=employee_headers)
    assert resp.status_code == 403

    admin_headers = register_and_login(client, "u_admin", role="admin")
    resp = client.get("/api/users", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
