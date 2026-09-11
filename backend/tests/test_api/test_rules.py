"""
规则接口测试（需测试DB）：CRUD全流程 + admin鉴权 + active_only过滤
"""
from tests.conftest import register_and_login, requires_db

RULE_PAYLOAD = {
    "name": "测试餐费限额",
    "code": "test_meal_limit",
    "rule_type": "amount_limit",
    "field_name": "amount",
    "operator": "gt",
    "threshold": "500",
    "severity": "warn",
    "risk_points": 20,
    "description": "单条餐费超500元警示",
}


@requires_db
def test_rules_require_auth(client):
    """未登录401"""
    assert client.get("/api/rules").status_code == 401


@requires_db
def test_rules_write_requires_admin(client):
    """非admin建规则403（登录可读列表）"""
    headers = register_and_login(client, "rl_fin", role="finance")
    assert client.get("/api/rules", headers=headers).status_code == 200
    assert client.post("/api/rules", json=RULE_PAYLOAD, headers=headers).status_code == 403


@requires_db
def test_rule_crud_flow(client, db_session):
    """admin：建→读→改→停用→active_only过滤→删"""
    admin_headers = register_and_login(client, "rl_adm", role="admin")

    resp = client.post("/api/rules", json=RULE_PAYLOAD, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    rule_id = resp.json()["id"]
    assert resp.json()["is_active"] is True

    resp = client.put(
        f"/api/rules/{rule_id}",
        json={"threshold": "800", "severity": "review"},
        headers=admin_headers,
    )
    assert resp.status_code == 200 and resp.json()["threshold"] == "800"

    # 停用后 active_only 不再返回
    client.put(f"/api/rules/{rule_id}", json={"is_active": False}, headers=admin_headers)
    all_ids = [r["id"] for r in client.get("/api/rules", headers=admin_headers).json()]
    active_ids = [
        r["id"] for r in client.get("/api/rules?active_only=true", headers=admin_headers).json()
    ]
    assert rule_id in all_ids and rule_id not in active_ids

    assert client.delete(f"/api/rules/{rule_id}", headers=admin_headers).status_code == 204
    assert client.delete(f"/api/rules/{rule_id}", headers=admin_headers).status_code == 404
