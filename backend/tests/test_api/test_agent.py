"""
AI审核接口测试（需测试DB）：workflow信息接口 + review权限/状态门槛（monkeypatch掉真工作流）
"""
from app.api.endpoints import agent as agent_module

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "agent接口测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "60.00",
            "expense_date": "2026-09-02",
            "invoice_no": "INV-AGENT-001",
        }
   ],
}


def _create_draft(client, username):
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    return resp.json()["id"], headers


@requires_db
def test_workflow_info(client):
    """工作流结构接口：登录即可读，返回nodes/edges"""
    headers = register_and_login(client, "ag_e1")
    resp = client.get("/api/agent/workflow", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "decision" in body["nodes"]
    assert any(e["to"] == "END" for e in body["edges"])


@requires_db
def test_review_cannot_touch_others_expense(client, db_session):
    """employee不能触发他人单据→403"""
    headers_owner = register_and_login(client, "ag_owner")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers_owner)
    other_id = resp.json()["id"]
    other_headers = register_and_login(client, "ag_e3")
    resp = client.post(
        "/api/agent/review", json={"expense_id": other_id}, headers=other_headers
    )
    assert resp.status_code == 403


@requires_db
def test_review_status_gate(client, db_session):
    """DRAFT状态不可触发审核→400（admin触发他人草稿）"""
    expense_id, _ = _create_draft(client, "ag_e4")
    admin_headers = register_and_login(client, "ag_adm4", role="admin")
    resp = client.post(
        "/api/agent/review", json={"expense_id": expense_id}, headers=admin_headers
    )
    assert resp.status_code == 400
    assert "不可审核" in resp.json()["detail"]


@requires_db
def test_review_success_with_fake_workflow(client, db_session, monkeypatch):
    """SUBMITTED状态+本人触发：monkeypatch工作流返回固定结果→200"""
    expense_id, headers = _create_draft(client, "ag_e5")
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    async def _fake_run(db, expense_id):
        return {
            "expense_id": expense_id, "risk_level": "low", "risk_score": 20.0,
            "decision": "auto_approve", "review_result": "{}", "suggestions": [],
            "relevant_rules": [], "similar_cases": [], "rule_violations": [],
            "workflow_errors": [], "elapsed_seconds": 0.1,
        }

    monkeypatch.setattr(agent_module, "workflow",
                        type("W", (), {"run": staticmethod(_fake_run)})())
    resp = client.post(
        "/api/agent/review", json={"expense_id": expense_id}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "auto_approve"
