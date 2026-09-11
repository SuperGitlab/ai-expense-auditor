"""
workflow落库回写 expense_items.invoice_verified 测试
FakeGraph固定document输出（含ocr_items），不走真实OCR/LLM
"""
import asyncio

from app.agents import workflow as wf
from app.models import ExpenseItem, ExpenseStatus

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "回写测试报销",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-WF-WB-001",
        }
    ],
}


class _FakeGraph:
    async def ainvoke(self, state, config=None):
        item_id = state["expense"]["items"][0]["id"]
        return {
            "risk": {"risk_score": 30.0, "risk_level": "low", "factors": []},
            "decision": {"action": "auto_approve", "reason": "低风险", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {
                "invoice_verified": True, "anomalies": [], "summary": "",
                "ocr_items": {item_id: {"verified": True, "anomalies": []}},
            },
            "errors": [],
        }


@requires_db
def test_invoice_verified_writeback(client, db_session, monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )
    headers = register_and_login(client, "wf_wb1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    asyncio.run(wf.workflow.run(db_session, expense_id))

    item = db_session.query(ExpenseItem).one()
    assert item.invoice_verified is True
    assert db_session.get(wf.Expense, expense_id).status == ExpenseStatus.APPROVED
