"""
AI审核工作流接线测试
monkeypatch掉LangGraph图与知识库,不调用真实LLM,验证:状态落库 + 申请人收到通知
"""
import asyncio

from app.agents import workflow as wf
from app.models import ExpenseStatus, Notification

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "接线测试报销",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-WF-NOTIFY-001",
        }
    ],
}


class _FakeGraph:
    """替身图:固定返回低风险自动通过"""
    async def ainvoke(self, state, config=None):
        return {
            "risk": {"risk_score": 30.0, "risk_level": "low", "factors": []},
            "decision": {"action": "auto_approve", "reason": "低风险单据", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {"invoice_verified": True, "anomalies": [], "summary": ""},
            "errors": [],
        }


@requires_db
def test_workflow_notifies_and_transitions(client, db_session, monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )

    headers = register_and_login(client, "wf_n1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    assert client.post(f"/api/expenses/{expense_id}/submit", headers=headers).status_code == 200

    asyncio.run(wf.workflow.run(db_session, expense_id))

    expense = db_session.get(wf.Expense, expense_id)
    assert expense.status == ExpenseStatus.APPROVED
    assert float(expense.risk_score) == 30.0

    note = db_session.query(Notification).one()
    assert note.type == "ai_review"
    assert "自动通过" in note.title
