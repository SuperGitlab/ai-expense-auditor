"""
断点恢复重跑接口测试：POST /api/agent/executions/{id}/retry
本人/admin/finance 对 SUBMITTED/PENDING 单派发 resume=True 任务（画布「重新执行」按钮后端）
"""
from app.models import AgentNodeRun, Expense, ExpenseStatus
from app.utils.helpers import utc_now

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "断点重跑测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-RETRY-001",
        }
    ],
}


def _submitted_expense(client, username: str) -> tuple[int, dict]:
    """建单并提交：conftest关闭了提交自动AI审核，单据停在SUBMITTED；返回(单据id, 申请人headers)"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text
    return expense_id, headers


def _patch_dispatch(monkeypatch, dispatched: list):
    from app.api.endpoints import agent as agent_module

    class _StubTask:
        def delay(self, expense_id, resume=False):
            dispatched.append((expense_id, resume))

    monkeypatch.setattr(agent_module, "_ensure_review_queue", lambda: None)
    monkeypatch.setattr(agent_module, "run_ai_review", _StubTask())


@requires_db
def test_retry_dispatches_with_resume(client, monkeypatch):
    """本人对SUBMITTED单重跑→派发(expense_id, resume=True)"""
    dispatched: list = []
    _patch_dispatch(monkeypatch, dispatched)
    expense_id, headers = _submitted_expense(client, "retry_e1")

    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"expense_id": expense_id, "dispatched": True, "resume": True}
    assert dispatched == [(expense_id, True)]


@requires_db
def test_retry_allowed_for_admin_and_finance(client, monkeypatch):
    """admin与finance可对他人单重跑"""
    dispatched: list = []
    _patch_dispatch(monkeypatch, dispatched)
    expense_id, _ = _submitted_expense(client, "retry_e2")

    admin = register_and_login(client, "retry_admin1", role="admin")
    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=admin)
    assert resp.status_code == 200, resp.text

    finance = register_and_login(client, "retry_fin1", role="finance")
    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=finance)
    assert resp.status_code == 200, resp.text
    assert dispatched == [(expense_id, True), (expense_id, True)]


@requires_db
def test_retry_forbidden_for_stranger(client, monkeypatch):
    """无关employee（非本人）不可重跑→403"""
    dispatched: list = []
    _patch_dispatch(monkeypatch, dispatched)
    expense_id, _ = _submitted_expense(client, "retry_e3")
    headers = register_and_login(client, "retry_stranger1")

    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=headers)

    assert resp.status_code == 403
    assert dispatched == []


@requires_db
def test_retry_rejected_on_terminal_status(client, db_session, monkeypatch):
    """终态（APPROVED）不可重跑→400"""
    dispatched: list = []
    _patch_dispatch(monkeypatch, dispatched)
    expense_id, _ = _submitted_expense(client, "retry_e4")
    expense = db_session.get(Expense, expense_id)
    expense.status = ExpenseStatus.APPROVED
    db_session.commit()
    headers = register_and_login(client, "retry_admin2", role="admin")

    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=headers)

    assert resp.status_code == 400
    assert dispatched == []


@requires_db
def test_retry_conflict_when_node_running(client, db_session, monkeypatch):
    """存在running节点（AI正执行）→409防双派发"""
    dispatched: list = []
    _patch_dispatch(monkeypatch, dispatched)
    expense_id, _ = _submitted_expense(client, "retry_e5")
    db_session.add(AgentNodeRun(
        expense_id=expense_id, node="document", status="running", started_at=utc_now(),
    ))
    db_session.commit()
    headers = register_and_login(client, "retry_admin3", role="admin")

    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=headers)

    assert resp.status_code == 409
    assert dispatched == []


@requires_db
def test_retry_missing_expense(client, monkeypatch):
    """不存在的报销单→404"""
    dispatched: list = []
    _patch_dispatch(monkeypatch, dispatched)
    headers = register_and_login(client, "retry_admin4", role="admin")

    resp = client.post("/api/agent/executions/999999/retry", headers=headers)

    assert resp.status_code == 404


@requires_db
def test_retry_queue_unavailable(client, monkeypatch):
    """队列探活失败（Redis未启动）→503"""
    from fastapi import HTTPException

    from app.api.endpoints import agent as agent_module

    def _boom():
        raise HTTPException(status_code=503, detail="AI审核队列不可用")

    monkeypatch.setattr(agent_module, "_ensure_review_queue", _boom)

    expense_id, headers = _submitted_expense(client, "retry_e6")

    resp = client.post(f"/api/agent/executions/{expense_id}/retry", headers=headers)

    assert resp.status_code == 503
