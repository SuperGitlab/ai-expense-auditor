"""
通知服务测试
核心契约：站内信落库必有 + 邮件尽力而为（失败不影响主流程）
"""
import pytest

from app.models import Notification, User
from app.services import notification_service
from app.services.notification_service import (notify_ai_review,
                                               notify_human_decision,
                                               notify_payment,
                                               send_notification)

from tests.conftest import requires_db


def _create_user(db, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@test.com",
        hashed_password="x",
        department="测试部",
    )
    db.add(user)
    db.commit()
    return user


def _create_expense(db, user: User, expense_no: str = "EXP-TEST-0001"):
    from app.models import Expense, ExpenseStatus
    expense = Expense(
        expense_no=expense_no,
        title="测试报销单",
        user_id=user.id,
        total_amount=100,
        status=ExpenseStatus.SUBMITTED,
    )
    db.add(expense)
    db.commit()
    return expense


@requires_db
def test_send_notification_creates_row(db_session):
    """站内信必须落库：标题/内容/类型/未读，返回True"""
    user = _create_user(db_session, "ns_u1")
    ok = send_notification(db_session, user.id, "标题A", "内容B", "approval")
    assert ok is True
    row = db_session.query(Notification).filter(Notification.user_id == user.id).one()
    assert row.title == "标题A"
    assert row.content == "内容B"
    assert row.type == "approval"
    assert row.is_read is False


@requires_db
def test_email_is_best_effort(db_session, monkeypatch):
    """邮件渠道失败不影响站内信落库，也不抛异常"""
    calls = []
    monkeypatch.setattr(
        notification_service, "notify",
        lambda email, title, content: calls.append((email, title)) or False,
    )
    user = _create_user(db_session, "ns_u2")
    ok = send_notification(db_session, user.id, "T", "C", "payment")
    assert ok is True
    assert calls == [(f"{user.username}@test.com", "T")]


@requires_db
def test_notify_ai_review_variants(db_session, monkeypatch):
    """三种AI裁决对应三种文案，type=ai_review"""
    monkeypatch.setattr(notification_service, "notify", lambda *a: False)
    user = _create_user(db_session, "ns_u3")
    expense = _create_expense(db_session, user)

    notification_service.notify_ai_review(db_session, expense, "auto_approve", "低风险")
    notification_service.notify_ai_review(db_session, expense, "auto_reject", "发票重复")
    notification_service.notify_ai_review(db_session, expense, "manual_review", "")

    rows = db_session.query(Notification).order_by(Notification.id).all()
    assert [r.type for r in rows] == ["ai_review"] * 3
    assert "自动通过" in rows[0].title
    assert "驳回" in rows[1].title and "发票重复" in rows[1].content
    assert "人工审批" in rows[2].title
    assert all(expense.expense_no in r.content for r in rows)


@requires_db
def test_notify_human_decision_and_payment(db_session, monkeypatch):
    monkeypatch.setattr(notification_service, "notify", lambda *a: False)
    user = _create_user(db_session, "ns_u4")
    expense = _create_expense(db_session, user, "EXP-TEST-0002")

    notify_human_decision(db_session, expense, approved=True, reason=None)
    notify_human_decision(db_session, expense, approved=False, reason="票据不全")
    notify_payment(db_session, expense)

    rows = db_session.query(Notification).order_by(Notification.id).all()
    assert "已通过" in rows[0].title
    assert "驳回" in rows[1].title and "票据不全" in rows[1].content
    assert rows[2].type == "payment" and "打款" in rows[2].title
