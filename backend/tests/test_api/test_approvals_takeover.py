"""
人工接管接口测试：AI执行中(SUBMITTED)/待初审(PENDING)/待终审(MANAGER_APPROVED)
审批人可随时直接裁决——人审优先；角色矩阵与两级审批一致，仅放宽状态门槛
"""
from app.models import (Approval, ApprovalAction, Expense, ExpenseStatus,
                        Notification)

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "人工接管测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-TAKE-001",
        }
    ],
}


def _submitted_expense(client, username: str = "take_e1") -> int:
    """建单并提交：conftest关闭了提交自动AI审核，单据停在SUBMITTED（=AI执行中）"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text
    return expense_id


def _takeover(client, headers, expense_id, action, comment=None):
    return client.post("/api/approvals/takeover", headers=headers, json={
        "expense_id": expense_id,
        "action": action,
        **({"comment": comment} if comment is not None else {}),
    })


def _login_other_department_manager(client, username: str):
    """注册并登录一个非测试部的经理（跨部门用）"""
    resp = client.post("/api/auth/register", json={
        "username": username,
        "email": f"{username}@test.com",
        "password": "pass123456",
        "full_name": username,
        "department": "市场部",
        "role": "manager",
    })
    assert resp.status_code == 201, resp.text
    resp = client.post("/api/auth/login-json", json={"username": username, "password": "pass123456"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@requires_db
def test_employee_cannot_takeover(client):
    """employee无审批权限→403"""
    expense_id = _submitted_expense(client, "take_emp")
    headers = register_and_login(client, "take_emp2")
    resp = _takeover(client, headers, expense_id, "approve", "看着没问题")
    assert resp.status_code == 403


@requires_db
def test_admin_takeover_approve_submitted(client, db_session):
    """admin对SUBMITTED越级接管通过→APPROVED（留痕[人工接管]+[管理员越级直批]）"""
    expense_id = _submitted_expense(client, "take_a1")
    headers = register_and_login(client, "take_admin1", role="admin")

    resp = _takeover(client, headers, expense_id, "approve", "紧急单据直批")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.APPROVED
    assert expense.approved_at is not None
    rec = [a for a in expense.approvals if a.action == ApprovalAction.APPROVE][-1]
    assert "[人工接管]" in rec.comment and "管理员越级直批" in rec.comment
    assert rec.step == "finance"

    # 申请人收到审批结果通知
    assert db_session.query(Notification).filter_by(
        user_id=expense.user_id, type="approval").count() == 1


@requires_db
def test_manager_takeover_approve_submitted(client, db_session):
    """本部门manager对SUBMITTED接管通过→MANAGER_APPROVED（视同初审，两级链不跳步）"""
    expense_id = _submitted_expense(client, "take_m1")
    headers = register_and_login(client, "take_mgr1", role="manager")

    resp = _takeover(client, headers, expense_id, "approve", "先审掉")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "manager_approved"

    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.MANAGER_APPROVED
    rec = [a for a in expense.approvals if a.action == ApprovalAction.APPROVE][-1]
    assert "[人工接管]" in rec.comment
    assert rec.step == "manager"


@requires_db
def test_manager_cannot_takeover_other_department(client):
    """manager只能接管本部门单据→跨部门403"""
    expense_id = _submitted_expense(client, "take_m2")  # 测试部员工
    headers = _login_other_department_manager(client, "take_mgr2")  # 市场部经理
    resp = _takeover(client, headers, expense_id, "approve", "越权")
    assert resp.status_code == 403


@requires_db
def test_finance_cannot_takeover_submitted(client):
    """finance对SUBMITTED接管→400（财务无初审权，两级链角色约束不变）"""
    expense_id = _submitted_expense(client, "take_f1")
    headers = register_and_login(client, "take_fin1", role="finance")
    resp = _takeover(client, headers, expense_id, "approve", "想直接过")
    assert resp.status_code == 400


@requires_db
def test_finance_takeover_final_approve(client, db_session):
    """finance对MANAGER_APPROVED接管通过→APPROVED（等价于终审）"""
    expense_id = _submitted_expense(client, "take_f2")
    headers = register_and_login(client, "take_fin2", role="finance")

    db = db_session
    expense = db.get(Expense, expense_id)
    expense.status = ExpenseStatus.MANAGER_APPROVED
    db.commit()

    resp = _takeover(client, headers, expense_id, "approve", "终审通过")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


@requires_db
def test_takeover_reject_requires_comment(client):
    """接管驳回必须填写意见→缺省400"""
    expense_id = _submitted_expense(client, "take_r1")
    headers = register_and_login(client, "take_admin2", role="admin")
    resp = _takeover(client, headers, expense_id, "reject")
    assert resp.status_code == 400


@requires_db
def test_takeover_reject_marks_rejected(client, db_session):
    """接管驳回→REJECTED：驳回原因落库、流水留痕、通知申请人"""
    expense_id = _submitted_expense(client, "take_r2")
    headers = register_and_login(client, "take_admin3", role="admin")

    resp = _takeover(client, headers, expense_id, "reject", "发票有问题")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"

    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.REJECTED
    assert expense.rejection_reason == "发票有问题"
    rec = [a for a in expense.approvals if a.action == ApprovalAction.REJECT][-1]
    assert "[人工接管]" in rec.comment and "发票有问题" in rec.comment

    assert db_session.query(Notification).filter_by(
        user_id=expense.user_id, type="approval").count() == 1


@requires_db
def test_takeover_rejected_on_terminal_state(client, db_session):
    """终态（已通过/已驳回/已支付）不可接管→400"""
    expense_id = _submitted_expense(client, "take_t1")
    headers = register_and_login(client, "take_admin4", role="admin")

    db = db_session
    expense = db.get(Expense, expense_id)
    for terminal in (ExpenseStatus.APPROVED, ExpenseStatus.REJECTED, ExpenseStatus.PAID):
        expense.status = terminal
        db.commit()
        resp = _takeover(client, headers, expense_id, "approve", "再批一次")
        assert resp.status_code == 400, f"{terminal} 应不可接管"


@requires_db
def test_takeover_missing_expense(client):
    """不存在的报销单→404"""
    headers = register_and_login(client, "take_admin5", role="admin")
    resp = _takeover(client, headers, 999999, "approve", "幽灵单")
    assert resp.status_code == 404
