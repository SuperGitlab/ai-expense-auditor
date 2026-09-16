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
    待审批列表（两级链）：
    manager 见 PENDING（本部门）；finance/admin 见 PENDING + MANAGER_APPROVED
    """
    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    query = db.query(Expense).filter(
        Expense.status.in_([ExpenseStatus.PENDING, ExpenseStatus.MANAGER_APPROVED])
    )
    # manager 只审本部门的初审队列；finance/admin 审全部两级队列
    if user.role == UserRole.MANAGER:
        from app.models.user import User as UserModel
        query = query.join(UserModel, Expense.user_id == UserModel.id).filter(
            UserModel.department == user.department,
            Expense.status == ExpenseStatus.PENDING,
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


def decide(db: Session, user: User, req: ApprovalDecisionRequest, *,
           takeover: bool = False) -> Expense:
    """
    两级审批决策（规则表）：
    manager: PENDING(本部门) approve→MANAGER_APPROVED / reject→REJECTED
    finance: MANAGER_APPROVED approve→APPROVED(写approved_at) / reject→REJECTED
    admin:   PENDING/MANAGER_APPROVED 越级直批→APPROVED（留痕）/ reject→REJECTED

    takeover=True（人工接管，人审优先）：额外允许 SUBMITTED（AI执行中），
    SUBMITTED 视同初审阶段走同一套流转；AI之后算出的结论不覆盖人工结果（workflow落库守卫）
    """
    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    expense = db.query(Expense).filter(Expense.id == req.expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail=f"报销单 {req.expense_id} 不存在")

    # 角色可操作状态表（takeover把SUBMITTED并入manager/admin的初审阶段门槛）
    if user.role == UserRole.MANAGER:
        allowed = {ExpenseStatus.PENDING}
        if takeover:
            allowed.add(ExpenseStatus.SUBMITTED)
    elif user.role == UserRole.FINANCE:
        allowed = {ExpenseStatus.MANAGER_APPROVED}
    else:  # admin：越级兜底，两级状态都可操作
        allowed = {ExpenseStatus.PENDING, ExpenseStatus.MANAGER_APPROVED}
        if takeover:
            allowed.add(ExpenseStatus.SUBMITTED)

    if expense.status not in allowed:
        hint = {
            UserRole.FINANCE: "财务终审需先经经理初审（当前状态 {s}）",
            UserRole.MANAGER: "当前状态 {s} 不可初审（仅待经理初审的单可操作）",
        }.get(user.role, "当前状态 {s} 不可审批")
        if takeover:
            hint = "当前状态 {s} 不可接管（仅AI执行中/待初审/待终审的单可操作）"
        raise HTTPException(status_code=400, detail=hint.format(s=expense.status.value))

    # manager 只能审本部门的单
    if user.role == UserRole.MANAGER:
        owner = expense.user
        if not owner or owner.department != user.department:
            raise HTTPException(status_code=403, detail="只能审批本部门的报销单")

    comment = req.comment
    if takeover:
        # 接管驳回必须给出理由（驳回直接终局，不许无理由否掉别人的单）
        if req.action == "reject" and not (req.comment or "").strip():
            raise HTTPException(status_code=400, detail="驳回必须填写审批意见")
        comment = f"[人工接管] {comment or ''}".strip()

    if req.action == "approve":
        # step：初审(manager)停在 MANAGER_APPROVED；到达 APPROVED 记 finance（admin越级同样记finance）
        is_first_review = (
            user.role == UserRole.MANAGER
            and expense.status in (ExpenseStatus.PENDING, ExpenseStatus.SUBMITTED)
        )
        step = "manager" if is_first_review else "finance"
        if user.role == UserRole.ADMIN and expense.status in (
            ExpenseStatus.PENDING, ExpenseStatus.SUBMITTED
        ):
            comment = f"[管理员越级直批] {comment or ''}".strip()
        expense.status = (
            ExpenseStatus.MANAGER_APPROVED if is_first_review else ExpenseStatus.APPROVED
        )
        if expense.status == ExpenseStatus.APPROVED:
            expense.approved_at = utc_now()
        expense.rejection_reason = None
        action = ApprovalAction.APPROVE
    else:
        step = ("manager" if expense.status in (ExpenseStatus.PENDING, ExpenseStatus.SUBMITTED)
                else "finance")
        expense.status = ExpenseStatus.REJECTED
        expense.rejection_reason = req.comment or "审批驳回（未填写原因）"
        action = ApprovalAction.REJECT

    db.add(Approval(
        expense_id=expense.id,
        approver_id=user.id,
        approver_name=user.full_name or user.username,
        action=action,
        comment=comment,
        step=step,
    ))
    db.commit()
    db.refresh(expense)
    # 通知申请人（站内信必有、邮件尽力而为；任何失败不影响审批结果）
    try:
        notify_human_decision(
            db, expense,
            approved=req.action == "approve",
            reason=req.comment, step=step,
        )
    except Exception as e:
        logger.warning(f"审批结果通知失败（不影响主流程）: {e}")
    logger.info(f"{user.username} {req.action}({step}) 报销单 {expense.expense_no}")
    return expense
