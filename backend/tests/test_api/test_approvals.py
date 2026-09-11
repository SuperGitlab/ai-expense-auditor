"""
审批接口测试（需测试DB）：两级审批链
经理初审(Pending→ManagerApproved) → 财务终审(→Approved)；admin越级；任一级驳回
"""
from app.models import Expense, ExpenseStatus

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


def _create_pending(client, db_session, username, status=ExpenseStatus.PENDING):
    """创建报销单并直改状态（模拟AI转人工），返回(单据ID, 申请人headers)"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    expense = db_session.get(Expense, expense_id)
    expense.status = status
    db_session.commit()
    return expense_id, headers


def _decide(client, headers, expense_id, action="approve", comment=None):
    return client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": action, "comment": comment},
        headers=headers,
    )


@requires_db
def test_employee_cannot_decide(client, db_session):
    """employee无审批权：decide 403、pending列表403"""
    expense_id, _ = _create_pending(client, db_session, "ap_e1")
    headers = register_and_login(client, "ap_emp")
    assert _decide(client, headers, expense_id).status_code == 403
    assert client.get("/api/approvals/pending", headers=headers).status_code == 403


@requires_db
def test_two_level_chain(client, db_session):
    """完整链：经理初审→manager_approved(step=manager)→财务终审→approved(step=finance,approved_at)"""
    expense_id, owner_headers = _create_pending(client, db_session, "ap_e2")
    manager_headers = register_and_login(client, "ap_mgr2", role="manager")
    finance_headers = register_and_login(client, "ap_fin2", role="finance")

    resp = _decide(client, manager_headers, expense_id, comment="初审通过")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "manager_approved"

    resp = _decide(client, finance_headers, expense_id, comment="终审通过")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    resp = client.get(f"/api/approvals/{expense_id}/history", headers=owner_headers)
    items = resp.json()["items"]
    steps = [(a["action"], a["step"]) for a in items if a["action"] == "approve"]
    assert ("approve", "manager") in steps and ("approve", "finance") in steps

    body = client.get(f"/api/expenses/{expense_id}", headers=owner_headers).json()
    assert body["approved_at"] is not None


@requires_db
def test_manager_reject(client, db_session):
    """经理初审驳回→rejected，原因落库"""
    expense_id, owner_headers = _create_pending(client, db_session, "ap_e3")
    manager_headers = register_and_login(client, "ap_mgr3", role="manager")
    assert _decide(client, manager_headers, expense_id, action="reject", comment="票据不齐").status_code == 200
    body = client.get(f"/api/expenses/{expense_id}", headers=owner_headers).json()
    assert body["status"] == "rejected" and "票据不齐" in (body["rejection_reason"] or "")


@requires_db
def test_finance_reject_at_final(client, db_session):
    """财务终审阶段驳回→rejected"""
    expense_id, _ = _create_pending(client, db_session, "ap_e4")
    manager_headers = register_and_login(client, "ap_mgr4", role="manager")
    finance_headers = register_and_login(client, "ap_fin4", role="finance")
    _decide(client, manager_headers, expense_id)
    assert _decide(client, finance_headers, expense_id, action="reject", comment="超预算").status_code == 200
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.REJECTED


@requires_db
def test_finance_cannot_first_review(client, db_session):
    """财务不可操作PENDING（须先过经理初审）→400"""
    expense_id, _ = _create_pending(client, db_session, "ap_e5")
    finance_headers = register_and_login(client, "ap_fin5", role="finance")
    resp = _decide(client, finance_headers, expense_id)
    assert resp.status_code == 400
    assert "初审" in resp.json()["detail"]


@requires_db
def test_admin_override_approve(client, db_session):
    """admin越级直批PENDING→approved（留痕step=finance）"""
    expense_id, _ = _create_pending(client, db_session, "ap_e6")
    admin_headers = register_and_login(client, "ap_adm6", role="admin")
    resp = _decide(client, admin_headers, expense_id, comment="紧急，越级直批")
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    items = client.get(
        f"/api/approvals/{expense_id}/history", headers=admin_headers
    ).json()["items"]
    rec = next(a for a in items if a["action"] == "approve")
    assert rec["step"] == "finance" and "越级" in (rec["comment"] or "")


@requires_db
def test_manager_cannot_final_review(client, db_session):
    """manager不可终审（不在其可操作状态）→400"""
    expense_id, _ = _create_pending(client, db_session, "ap_e7")
    manager_headers = register_and_login(client, "ap_mgr7", role="manager")
    resp = _decide(client, manager_headers, expense_id)
    assert resp.status_code == 200  # 初审通过
    resp = _decide(client, manager_headers, expense_id)  # 再操作manager_approved
    assert resp.status_code == 400


@requires_db
def test_cannot_decide_submitted(client, db_session):
    """SUBMITTED（未进人工链）任何人不可审→400"""
    headers = register_and_login(client, "ap_e8")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    admin_headers = register_and_login(client, "ap_adm8", role="admin")
    assert _decide(client, admin_headers, expense_id).status_code == 400


@requires_db
def test_manager_other_department_403(client, db_session):
    """manager不能审其他部门：注册后改库中部门实现跨部门"""
    from app.models import User
    expense_id, _ = _create_pending(client, db_session, "ap_e9")
    other_headers = register_and_login(client, "ap_mgr9", role="manager")
    other = db_session.query(User).filter(User.username == "ap_mgr9").first()
    other.department = "别的部门"
    db_session.commit()
    assert _decide(client, other_headers, expense_id).status_code == 403


@requires_db
def test_list_pending_scopes(client, db_session):
    """manager见PENDING(本部门)；finance/admin见PENDING+MANAGER_APPROVED"""
    pending_id, _ = _create_pending(client, db_session, "ap_e10")
    final_id, _ = _create_pending(
        client, db_session, "ap_e10b", status=ExpenseStatus.MANAGER_APPROVED
    )
    manager_headers = register_and_login(client, "ap_mgr10", role="manager")
    data = client.get("/api/approvals/pending", headers=manager_headers).json()
    ids = [e["id"] for e in data]
    assert pending_id in ids and final_id not in ids
    # 返回项带status，前端分组用
    statuses = {e["id"]: e["status"] for e in data}
    assert statuses[pending_id] == "pending"

    finance_headers = register_and_login(client, "ap_fin10", role="finance")
    ids = [e["id"] for e in client.get("/api/approvals/pending", headers=finance_headers).json()]
    assert pending_id in ids and final_id in ids
