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


def list_running(db: Session, user: User) -> List[Expense]:

    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    query = db.query(Expense).filter(Expense.status == ExpenseStatus.SUBMITTED)
    # manager 与初审队列同口径：只看本部门
    if user.role == UserRole.MANAGER:
        from app.models.user import User as UserModel
        query = query.join(UserModel, Expense.user_id == UserModel.id).filter(
            UserModel.department == user.department,
        )
    return query.order_by(Expense.submitted_at.asc()).all()


def get_history(db: Session, expense_id: int) -> List[Approval]:

    return (
        db.query(Approval)
        .filter(Approval.expense_id == expense_id)
        .order_by(Approval.created_at.asc(), Approval.id.asc())
        .all()
    )


def decide(db: Session, user: User, req: ApprovalDecisionRequest, *,
           takeover: bool = False) -> Expense:

    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    expense = db.query(Expense).filter(Expense.id == req.expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail=f"报销单 {req.expense_id} 不存在")

    # 角色可操作状态表（takeover=紧急放行通道：SUBMITTED/PENDING也可接管）
    if user.role == UserRole.MANAGER:
        allowed = {ExpenseStatus.PENDING}
        if takeover:
            allowed.add(ExpenseStatus.SUBMITTED)
    elif user.role == UserRole.FINANCE:
        allowed = {ExpenseStatus.MANAGER_APPROVED}
        if takeover:
            # 紧急报销快速通道：跳过经理初审直达终审
            allowed |= {ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING}
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
        # step：初审(manager)停在 MANAGER_APPROVED；到达 APPROVED 记 finance（admin/finance越级同样记finance）
        is_first_review = (
            user.role == UserRole.MANAGER
            and expense.status in (ExpenseStatus.PENDING, ExpenseStatus.SUBMITTED)
        )
        step = "manager" if is_first_review else "finance"
        if user.role in (UserRole.ADMIN, UserRole.FINANCE) and expense.status in (
            ExpenseStatus.PENDING, ExpenseStatus.SUBMITTED
        ):
            prefix = "管理员越级直批" if user.role == UserRole.ADMIN else "财务越级直批"
            comment = f"[{prefix}] {comment or ''}".strip()
        expense.status = (
            ExpenseStatus.MANAGER_APPROVED if is_first_review else ExpenseStatus.APPROVED
        )
        if expense.status == ExpenseStatus.APPROVED:
            expense.approved_at = utc_now()
        expense.rejection_reason = None
        action = ApprovalAction.APPROVE
    else:
        # step按角色推导：manager驳回=初审职责；finance/admin驳回=终审职责（与approve路径一致）
        step = "manager" if user.role == UserRole.MANAGER else "finance"
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
    # 人审落定→画布立即以人为主：未完成AI节点标overridden（失败不影响审批本身）
    try:
        from app.agents.workflow import mark_nodes_human_first
        mark_nodes_human_first(db, expense.id, expense.status.value)
    except Exception as e:
        logger.warning("人审优先节点标记失败（不影响审批）: 报销单%s, err=%s", expense.expense_no, e)
    # 通知申请人（站内信必有、邮件尽力而为；任何失败不影响审批结果）
    try:
        notify_human_decision(
            db, expense,
            approved=req.action == "approve",
            reason=req.comment, step=step,
        )
    except Exception as e:
        logger.warning("审批结果通知失败（不影响主流程）: 报销单%s, err=%s", expense.expense_no, e)
    logger.info("%s %s(%s) 报销单 %s", user.username, req.action, step, expense.expense_no)
    return expense
