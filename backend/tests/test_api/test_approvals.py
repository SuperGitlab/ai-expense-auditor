"""
审批接口测试（需测试DB）
"""
from tests.conftest import register_and_login, requires_db

EXPENSE_PAYLOAD = {
    "title": "招待费报销",
    "expense_type": "meal",
    "description": "客户招待",
    "items": [
        {
            "category_id": 2,
            "description": "客户工作餐",
            "amount": "380.00",
            "expense_date": "2026-08-25",
            "invoice_no": "INV11112222",
        }
    ],
}


def _create_submitted(client, username):
    """辅助：创建并提交一张报销单，返回(单据ID, 申请人headers)"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    assert resp.status_code == 200
    return expense_id, headers


@requires_db
def test_employee_cannot_decide(client):
    """employee无审批权：decide返回403、pending列表403"""
    expense_id, _ = _create_submitted(client, "ap_e1")
    headers = register_and_login(client, "ap_emp")
    resp = client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "approve", "comment": "同意"},
        headers=headers,
    )
    assert resp.status_code == 403
    resp = client.get("/api/approvals/pending", headers=headers)
    assert resp.status_code == 403


@requires_db
def test_finance_approve_flow(client):
    """finance审批通过：状态approved、历史含APPROVE记录"""
    expense_id, owner_headers = _create_submitted(client, "ap_e2")
    finance_headers = register_and_login(client, "ap_fin", role="finance")

    resp = client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "approve", "comment": "合规，通过"},
        headers=finance_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(f"/api/expenses/{expense_id}", headers=owner_headers)
    assert resp.json()["status"] == "approved"

    resp = client.get(f"/api/approvals/{expense_id}/history", headers=owner_headers)
    actions = [a["action"] for a in resp.json()["items"]]
    assert "approve" in actions


@requires_db
def test_finance_reject_flow(client):
    """finance驳回：状态rejected、驳回原因落库"""
    expense_id, owner_headers = _create_submitted(client, "ap_e3")
    finance_headers = register_and_login(client, "ap_fin2", role="finance")

    resp = client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "reject", "comment": "发票信息不全"},
        headers=finance_headers,
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/expenses/{expense_id}", headers=owner_headers)
    body = resp.json()
    assert body["status"] == "rejected"
    assert "发票信息不全" in (body["rejection_reason"] or "")


@requires_db
def test_cannot_decide_twice(client):
    """已审批单不可重复审批：第二次decide返回400"""
    expense_id, _ = _create_submitted(client, "ap_e4")
    finance_headers = register_and_login(client, "ap_fin3", role="finance")
    client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "approve"},
        headers=finance_headers,
    )
    resp = client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "approve"},
        headers=finance_headers,
    )
    assert resp.status_code == 400
