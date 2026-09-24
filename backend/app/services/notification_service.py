"""
通知服务
核心契约：站内信落库必有；邮件尽力而为（复用notification_tool，失败仅告警）
"""
import logging

from sqlalchemy.orm import Session

from app.models import Expense, Notification, User
from app.tools.notification_tool import notify

logger = logging.getLogger(__name__)


def send_notification(db: Session, user_id: int, title: str, content: str, ntype: str) -> bool:
    """
    发送通知：站内信落库（必有） + 邮件（尽力而为）

    注意：内部会 commit 当前会话，请在业务事务提交后调用（避免部分提交调用方的未落库变更）。

    Returns:
        bool: 站内信是否落库成功（邮件结果不影响返回值）
    """
    try:
        db.add(Notification(user_id=user_id, title=title, content=content, type=ntype))
        db.commit()
    except Exception as e:
        logger.exception("站内信落库失败: user=%s, title=%s, err=%s", user_id, title, e)
        db.rollback()
        return False

    try:
        user = db.get(User, user_id)
        if user and user.email:
            notify(user.email, title, content)
    except Exception as e:
        logger.warning("邮件通知失败（不影响主流程）: user=%s, err=%s", user_id, e)
    return True


def notify_ai_review(db: Session, expense: Expense, action: str, reason: str) -> None:
    """AI审核结果通知申请人"""
    no = expense.expense_no
    mapping = {
        "auto_approve": ("报销单自动通过", f"您的报销单 {no} 已通过AI审核，自动通过，等待财务打款。"),
        "auto_reject": ("报销单被驳回（AI审核）", f"您的报销单 {no} 未通过AI审核，已驳回。\n原因：{reason or '未提供'}"),
        "manual_review": ("报销单转人工审批", f"您的报销单 {no} 已转人工审批，请等待审批人处理。"),
    }
    title, content = mapping.get(action, ("报销单审核进展", f"您的报销单 {no} 审核状态更新：{action}"))
    send_notification(db, expense.user_id, title, content, "ai_review")


def notify_human_decision(db: Session, expense: Expense, approved: bool,
                          reason: str | None, step: str | None = None) -> None:
    """人工审批结果通知申请人（step区分初审/终审文案）"""
    no = expense.expense_no
    if approved:
        if step == "manager":
            title, content = "报销单已通过经理初审", f"您的报销单 {no} 已通过经理初审，等待财务终审。"
        else:
            title, content = "报销单已通过财务终审", f"您的报销单 {no} 已完成全部审批，等待财务打款。"
    else:
        stage = "经理初审" if step == "manager" else "财务终审"
        title, content = "报销单被驳回", f"您的报销单 {no} 在{stage}环节被驳回。\n原因：{reason or '未填写'}"
    send_notification(db, expense.user_id, title, content, "approval")


def notify_payment(db: Session, expense: Expense) -> None:
    """打款登记完成通知申请人"""
    send_notification(
        db, expense.user_id, "报销款已打款",
        f"您的报销单 {expense.expense_no} 已完成打款登记，金额 {expense.total_amount} 元。",
        "payment",
    )
