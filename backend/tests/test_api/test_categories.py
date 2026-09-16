"""
类别接口测试（需测试DB）：CRUD全流程 + admin鉴权 + include_inactive + 删除语义
（删除=绑定规则停用解绑；有历史明细时转停用不物理删）
"""
from tests.conftest import register_and_login, requires_db

CATEGORY_PAYLOAD = {
    "name": "培训费",
    "code": "training",
    "max_amount": 2000,
    "description": "培训课程、认证考试",
}

EXPENSE_WITH_MEAL = {
    "title": "历史引用测试单",
    "expense_type": "travel",
    "description": "测试历史引用",
    "items": [
        {
            "category_id": 2,  # conftest种子：餐饮费
            "description": "工作餐",
            "amount": "88.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV_CAT_HIST1",
        }
    ],
}


@requires_db
def test_categories_require_auth(client):
    assert client.get("/api/categories").status_code == 401
    assert client.post("/api/categories", json=CATEGORY_PAYLOAD).status_code == 401


@requires_db
def test_categories_list_contains_seeds(client):
    """种子数据含差旅费/餐饮费（conftest种子id 1/2）"""
    headers = register_and_login(client, "cat_e1")
    resp = client.get("/api/categories", headers=headers)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "差旅费" in names and "餐饮费" in names


@requires_db
def test_category_write_requires_admin(client):
    """非admin：建/改/删 403；include_inactive 也 403"""
    headers = register_and_login(client, "cat_emp", role="employee")
    assert client.post("/api/categories", json=CATEGORY_PAYLOAD, headers=headers).status_code == 403
    assert client.put("/api/categories/1", json={"name": "x"}, headers=headers).status_code == 403
    assert client.delete("/api/categories/1", headers=headers).status_code == 403
    assert (
        client.get("/api/categories?include_inactive=true", headers=headers).status_code == 403
    )


@requires_db
def test_category_crud_flow(client):
    """admin：建→409重复→改（code不可改）→停用过滤→物理删"""
    admin = register_and_login(client, "cat_adm", role="admin")

    resp = client.post("/api/categories", json=CATEGORY_PAYLOAD, headers=admin)
    assert resp.status_code == 201, resp.text
    cat = resp.json()
    assert cat["is_active"] is True and cat["code"] == "training"

    # code 重复
    assert client.post("/api/categories", json=CATEGORY_PAYLOAD, headers=admin).status_code == 409

    # 部分更新：改名+改限额；payload带code也被忽略（创建后不可改）
    resp = client.put(
        f"/api/categories/{cat['id']}",
        json={"name": "培训及认证费", "max_amount": 3000, "code": "hack"},
        headers=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "培训及认证费"
    assert resp.json()["max_amount"] == 3000
    assert resp.json()["code"] == "training"

    # 停用后默认列表消失、include_inactive 能看到（响应带is_active）
    client.put(f"/api/categories/{cat['id']}", json={"is_active": False}, headers=admin)
    names = [c["name"] for c in client.get("/api/categories", headers=admin).json()]
    assert "培训及认证费" not in names
    all_cats = client.get("/api/categories?include_inactive=true", headers=admin).json()
    match = next(c for c in all_cats if c["id"] == cat["id"])
    assert match["is_active"] is False

    # 无任何引用 → 物理删除
    resp = client.delete(f"/api/categories/{cat['id']}", headers=admin)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "hidden_rules": 0, "has_history": False}
    assert client.delete(f"/api/categories/{cat['id']}", headers=admin).status_code == 404


@requires_db
def test_delete_hides_bound_rules(client):
    """删除类别：绑定规则停用+解绑（规则行保留，hidden_rules计数）"""
    admin = register_and_login(client, "cat_adm2", role="admin")
    cat_id = client.post("/api/categories", json=CATEGORY_PAYLOAD, headers=admin).json()["id"]

    def _rule(code):
        return {
            "name": f"规则{code}",
            "code": code,
            "rule_type": "amount_limit",
            "category_id": cat_id,
            "field_name": "amount",
            "operator": "gt",
            "threshold": "100",
            "severity": "warn",
            "risk_points": 10,
        }

    assert client.post("/api/rules", json=_rule("CAT_R1"), headers=admin).status_code == 201
    assert client.post("/api/rules", json=_rule("CAT_R2"), headers=admin).status_code == 201

    resp = client.delete(f"/api/categories/{cat_id}", headers=admin)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "hidden_rules": 2, "has_history": False}

    rules = {
        r["code"]: r for r in client.get("/api/rules", headers=admin).json()
    }
    for code in ("CAT_R1", "CAT_R2"):
        assert rules[code]["is_active"] is False
        assert rules[code]["category_id"] is None


@requires_db
def test_delete_with_history_deactivates(client):
    """有历史明细的类别：不物理删（外键保护），转停用，明细保留"""
    admin = register_and_login(client, "cat_adm3", role="admin")
    user = register_and_login(client, "cat_user3")

    exp = client.post("/api/expenses", json=EXPENSE_WITH_MEAL, headers=user)
    assert exp.status_code == 201, exp.text

    resp = client.delete("/api/categories/2", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is False and body["has_history"] is True

    # 默认列表消失、include_inactive 行还在（历史单据的类别名仍可解析）
    ids = [c["id"] for c in client.get("/api/categories", headers=admin).json()]
    assert 2 not in ids
    ids_all = [c["id"] for c in client.get("/api/categories?include_inactive=true", headers=admin).json()]
    assert 2 in ids_all

    # 历史明细原样保留
    detail = client.get(f"/api/expenses/{exp.json()['id']}", headers=user).json()
    assert len(detail["items"]) == 1
    assert detail["items"][0]["description"] == "工作餐"
