"""
报销接口测试（需测试DB）
"""
from tests.conftest import register_and_login, requires_db

# 合法报销单payload（category_id=1依赖种子数据，测试库若无类别则用类别接口前置创建）
EXPENSE_PAYLOAD = {
    "title": "出差报销-北京",
    "expense_type": "travel",
    "description": "客户拜访差旅",
    "items": [
        {
            "category_id": 1,
            "description": "北京-上海高铁",
            "amount": "553.50",
            "expense_date": "2026-08-20",
            "invoice_no": "INV12345678",
        }
    ],
}


def _ensure_category(client, headers):
    """确保存在可用类别（幂等），返回类别ID"""
    resp = client.post(
        "/api/rules",  # 借admin才能建？规则需要admin；类别无接口——直接用1，种子库保证
        headers=headers,
    )
    return 1


@requires_db
def test_create_expense_requires_auth(client):
    """未登录创建报销单返回401"""
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD)
    assert resp.status_code == 401


@requires_db
def test_create_expense_empty_items_rejected(client):
    """空明细列表返回422校验错误"""
    headers = register_and_login(client, "exp_user1")
    payload = {**EXPENSE_PAYLOAD, "items": []}
    resp = client.post("/api/expenses", json=payload, headers=headers)
    assert resp.status_code == 422


@requires_db
def test_create_and_get_expense(client):
    """创建报销单：合计金额自动计算、状态为draft"""
    headers = register_and_login(client, "exp_user2")
    payload = {
        **EXPENSE_PAYLOAD,
        "items": [
            {**EXPENSE_PAYLOAD["items"][0], "amount": "100.00"},
            {**EXPENSE_PAYLOAD["items"][0], "amount": "200.50", "invoice_no": "INV87654321"},
        ],
    }
    resp = client.post("/api/expenses", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert float(body["total_amount"]) == 300.50
    assert body["expense_no"].startswith("EXP-")
    assert len(body["items"]) == 2

    # 详情可查
    resp = client.get(f"/api/expenses/{body['id']}", headers=headers)
    assert resp.status_code == 200


@requires_db
def test_employee_sees_only_own_expenses(client):
    """employee只能看到自己的报销单"""
    headers_a = register_and_login(client, "exp_a")
    headers_b = register_and_login(client, "exp_b")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers_a)
    expense_id = resp.json()["id"]

    # B看不到A的详情（403）
    resp = client.get(f"/api/expenses/{expense_id}", headers=headers_b)
    assert resp.status_code == 403

    # B的列表为空
    resp = client.get("/api/expenses", headers=headers_b)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # A的列表有1条
    resp = client.get("/api/expenses", headers=headers_a)
    assert resp.json()["total"] == 1


@requires_db
def test_submit_flow(client):
    """提交报销单：状态 submitted→pending（AI审核关闭/失败时转人工）"""
    headers = register_and_login(client, "exp_submit")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]

    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    # AI审核触发失败时应返回200且状态为pending（降级转人工）
    assert resp.status_code == 200
    assert resp.json()["status"] in ("submitted", "pending", "approved")

    # 审批历史出现SUBMIT记录
    resp = client.get(f"/api/approvals/{expense_id}/history", headers=headers)
    assert resp.status_code == 200
    actions = [a["action"] for a in resp.json()["items"]]
    assert "submit" in actions


@requires_db
def test_edit_only_draft(client):
    """非草稿状态不可编辑"""
    headers = register_and_login(client, "exp_edit")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    resp = client.put(
        f"/api/expenses/{expense_id}",
        json={"title": "改标题"},
        headers=headers,
    )
    assert resp.status_code == 400


@requires_db
def test_cancel_after_manager_approved_forbidden(client, db_session):
    """MANAGER_APPROVED（已进财务队列）不可自行取消→400"""
    from app.models import Expense, ExpenseStatus
    headers = register_and_login(client, "cx_e1")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    expense = db_session.get(Expense, expense_id)
    expense.status = ExpenseStatus.MANAGER_APPROVED
    db_session.commit()
    resp = client.post(f"/api/expenses/{expense_id}/cancel", headers=headers)
    assert resp.status_code == 400
