"""
审批业务服务
待审列表、审批历史、人工审批决策
"""
import logging
from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (Approval, ApprovalAction, Expense, ExpenseStatus,
                        User, UserRole)
from app.schemas.approval import ApprovalDecisionRequest
from app.services.notification_service import notify_human_decision
from app.utils.helpers import utc_now

logger = logging.getLogger(__name__)


def list_pending(db: Session, user: User) -> List[Expense]:
    """
    待审批列表（finance/manager）：
    AI审核后转人工的报销单（PENDING状态）
    """
    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    query = db.query(Expense).filter(Expense.status == ExpenseStatus.PENDING)
    # manager 只审本部门；finance/admin 审全部
    if user.role == UserRole.MANAGER:
        from app.models.user import User as UserModel
        query = query.join(UserModel, Expense.user_id == UserModel.id).filter(
            UserModel.department == user.department
        )
    return query.order_by(Expense.submitted_at.asc()).all()


def get_history(db: Session, expense_id: int) -> List[Approval]:
    """报销单审批历史（按时间正序）"""
    return (
        db.query(Approval)
        .filter(Approval.expense_id == expense_id)
        .order_by(Approval.created_at.asc(), Approval.id.asc())
        .all()
    )


def decide(db: Session, user: User, req: ApprovalDecisionRequest) -> Expense:
    """
    人工审批决策：
    权限校验 → 状态机校验（SUBMITTED/PENDING可审）→ 更新报销单状态 → 写审批记录
    """
    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    expense = db.query(Expense).filter(Expense.id == req.expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail=f"报销单 {req.expense_id} 不存在")

    if expense.status not in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {expense.status.value} 不可审批（仅待审核状态可操作）",
        )

    # manager 只能审本部门的单
    if user.role == UserRole.MANAGER:
        owner = expense.user
        if not owner or owner.department != user.department:
            raise HTTPException(status_code=403, detail="只能审批本部门的报销单")

    if req.action == "approve":
        expense.status = ExpenseStatus.APPROVED
        expense.approved_at = utc_now()
        expense.rejection_reason = None
        action = ApprovalAction.APPROVE
    else:
        expense.status = ExpenseStatus.REJECTED
        expense.rejection_reason = req.comment or "审批驳回（未填写原因）"
        action = ApprovalAction.REJECT

    db.add(Approval(
        expense_id=expense.id,
        approver_id=user.id,
        approver_name=user.full_name or user.username,
        action=action,
        comment=req.comment,
    ))
    db.commit()
    db.refresh(expense)
    # 通知申请人（站内信必有、邮件尽力而为；任何失败不影响审批结果）
    try:
        notify_human_decision(db, expense, approved=req.action == "approve", reason=req.comment)
    except Exception as e:
        logger.warning(f"审批结果通知失败（不影响主流程）: {e}")
    logger.info(f"{user.username} {req.action} 报销单 {expense.expense_no}")
    return expense
