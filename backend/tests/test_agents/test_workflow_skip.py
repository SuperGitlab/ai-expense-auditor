"""
workflow manual_review 落库分流测试：
部门有在职经理→PENDING；申请人本人是经理/部门无经理→直接MANAGER_APPROVED(留痕)
"""
import asyncio

from app.agents import workflow as wf
from app.models import Expense, ExpenseStatus

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "跳过初审测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-SKIP-001",
        }
    ],
}


class _FakeGraph:
    """替身图:固定返回manual_review"""
    async def ainvoke(self, state, config=None):
        return {
            "risk": {"risk_score": 60.0, "risk_level": "medium", "factors": []},
            "decision": {"action": "manual_review", "reason": "中风险", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {"invoice_verified": True, "anomalies": [], "summary": "",
                         "ocr_items": {}},
            "errors": [],
        }


def _setup(monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )


@requires_db
def test_lands_pending_when_manager_exists(client, db_session, monkeypatch):
    """部门有在职经理（测试部）→PENDING"""
    _setup(monkeypatch)
    register_and_login(client, "sk_mgr0", role="manager")  # 测试部在职经理
    headers = register_and_login(client, "sk_e1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    asyncio.run(wf.workflow.run(db_session, expense_id))
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.PENDING


@requires_db
def test_skips_when_no_manager_in_department(client, db_session, monkeypatch):
    """部门无在职经理→直接MANAGER_APPROVED，且留痕Approval(step=manager)"""
    _setup(monkeypatch)
    headers = register_and_login(client, "sk_e2")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    asyncio.run(wf.workflow.run(db_session, expense_id))
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.MANAGER_APPROVED
    rec = [a for a in expense.approvals if a.step == "manager"]
    assert rec and "跳过" in (rec[0].comment or "")


@requires_db
def test_skips_when_applicant_is_manager(client, db_session, monkeypatch):
    """申请人本人是经理（不能自审）→直接MANAGER_APPROVED"""
    _setup(monkeypatch)
    headers = register_and_login(client, "sk_mgr3", role="manager")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    asyncio.run(wf.workflow.run(db_session, expense_id))
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.MANAGER_APPROVED
