"""
人审优先守卫测试：AI执行期间人工已接管（状态离开SUBMITTED）→
workflow落库段不得覆盖人的裁决：状态原样、AI字段不落地、AI结论仅留档、决策节点标overridden
"""
import asyncio

from app.agents import workflow as wf
from app.models import (AgentNodeRun, Approval, ApprovalAction, Expense,
                        ExpenseStatus, Notification)

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "人审优先竞态测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-RACE-001",
        }
    ],
}


class _FakeGraph:
    """替身图：AI判定自动通过——若守卫失效会把人工驳回覆盖成approved"""
    async def ainvoke(self, state, config=None):
        return {
            "risk": {"risk_score": 20.0, "risk_level": "low", "factors": []},
            "decision": {"action": "auto_approve", "reason": "低风险单据", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {"invoice_verified": True, "anomalies": [], "summary": ""},
            "errors": [],
        }


def _setup(monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )


@requires_db
def test_human_rejection_wins_over_ai(client, db_session, monkeypatch):
    """AI判通过 vs 人工先驳回：状态保持REJECTED，AI结论只进流水留档"""
    _setup(monkeypatch)
    headers = register_and_login(client, "race_e1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    # 模拟AI执行期间人工接管驳回（人审动作已在别处提交生效）
    expense = db_session.get(Expense, expense_id)
    expense.status = ExpenseStatus.REJECTED
    expense.rejection_reason = "人工接管驳回"
    db_session.commit()

    asyncio.run(wf.workflow.run(db_session, expense_id))

    db_session.expire_all()
    expense = db_session.get(Expense, expense_id)
    assert expense.status == ExpenseStatus.REJECTED          # 人的裁决未被覆盖
    assert expense.rejection_reason == "人工接管驳回"
    assert expense.approved_at is None
    assert expense.risk_score is None                        # AI字段不落地（只在流水留档）
    assert expense.risk_level is None
    assert expense.ai_review_result is None

    # AI结论仍留档：AI_REVIEW流水照写，含风险分与AI裁决
    ai_rows = [a for a in expense.approvals if a.action == ApprovalAction.AI_REVIEW]
    assert ai_rows and ai_rows[-1].ai_decision == "auto_approve"
    assert float(ai_rows[-1].risk_score) == 20.0
    assert ai_rows[-1].approver_name == "AI审核系统"

    # 决策节点标记被人审覆盖
    node = db_session.query(AgentNodeRun).filter_by(
        expense_id=expense_id, node="decision").one()
    assert node.status == "overridden"
    assert "人审结果优先" in (node.detail or "")

    # 不给申请人发"AI自动通过"通知（人的结果才是终局）
    assert db_session.query(Notification).filter_by(
        user_id=expense.user_id, type="ai_review").count() == 0


@requires_db
def test_normal_path_still_lands_when_submitted(client, db_session, monkeypatch):
    """守卫不影响正常路径：仍是SUBMITTED时AI结果照常落库生效"""
    _setup(monkeypatch)
    headers = register_and_login(client, "race_e2")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    asyncio.run(wf.workflow.run(db_session, expense_id))

    db_session.expire_all()
    expense = db_session.get(Expense, expense_id)
    assert expense.status == ExpenseStatus.APPROVED
    assert float(expense.risk_score) == 20.0


@requires_db
def test_pending_expense_still_lands(client, db_session, monkeypatch):
    """PENDING=Celery失败兜底态（尚无人工决定），重跑/断点恢复的AI结果应照常落库生效"""
    _setup(monkeypatch)
    headers = register_and_login(client, "race_e3")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    # 模拟上一轮Celery任务异常兜底：SUBMITTED → PENDING（转人工队列）
    expense = db_session.get(Expense, expense_id)
    expense.status = ExpenseStatus.PENDING
    db_session.commit()

    asyncio.run(wf.workflow.run(db_session, expense_id))

    db_session.expire_all()
    expense = db_session.get(Expense, expense_id)
    assert expense.status == ExpenseStatus.APPROVED      # 按AI裁决流转，不被守卫拦成只留档
    assert float(expense.risk_score) == 20.0
    assert expense.risk_level == "low"
    ai_rows = [a for a in expense.approvals if a.action == ApprovalAction.AI_REVIEW]
    assert ai_rows and ai_rows[-1].ai_decision == "auto_approve"
