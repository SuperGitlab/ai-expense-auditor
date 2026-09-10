"""
报销业务服务
报销单的创建、查询、修改、提交
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import (Approval, ApprovalAction, Category, Expense,
                        ExpenseItem, ExpenseStatus, ExpenseType, User,
                        UserRole)
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.services.notification_service import notify_payment
from app.utils.helpers import generate_expense_no, utc_now

logger = logging.getLogger(__name__)


def _get_or_404(db: Session, expense_id: int) -> Expense:
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail=f"报销单 {expense_id} 不存在")
    return expense


def _check_read_permission(expense: Expense, user: User) -> None:
    """读取权限：本人可看自己的；finance/admin 可看全部；manager 可看本部门"""
    if user.role in (UserRole.FINANCE, UserRole.ADMIN):
        return
    if expense.user_id == user.id:
        return
    if user.role == UserRole.MANAGER:
        owner = expense.user
        if owner and owner.department == user.department:
            return
    raise HTTPException(status_code=403, detail="无权查看该报销单")


def _validate_categories(db: Session, category_ids: list[int]) -> None:
    """校验费用类别存在且启用"""
    for cid in set(category_ids):
        cat = db.get(Category, cid)
        if not cat or not cat.is_active:
            raise HTTPException(status_code=400, detail=f"费用类别 {cid} 不存在或已停用")


def create_expense(db: Session, user: User, data: ExpenseCreate) -> Expense:
    """创建报销单（自动汇总items金额写入total_amount）"""
    _validate_categories(db, [item.category_id for item in data.items])

    total = sum((item.amount for item in data.items), Decimal("0"))
    expense = Expense(
        expense_no=generate_expense_no(),
        title=data.title,
        user_id=user.id,
        expense_type=data.expense_type,
        total_amount=total,
        description=data.description,
        remark=data.remark,
        status=ExpenseStatus.DRAFT,
    )
    db.add(expense)
    db.flush()  # 拿到expense.id

    for item in data.items:
        db.add(ExpenseItem(
            expense_id=expense.id,
            category_id=item.category_id,
            description=item.description,
            amount=item.amount,
            expense_date=item.expense_date,
            invoice_no=item.invoice_no,
            invoice_url=item.invoice_url,
        ))
    db.commit()
    db.refresh(expense)
    logger.info(f"用户 {user.username} 创建报销单 {expense.expense_no} 金额 {total}")
    return expense


def list_expenses(
    db: Session,
    user: User,
    page: int = 1,
    page_size: int = 10,
    status: Optional[ExpenseStatus] = None,
    expense_type: Optional[ExpenseType] = None,
) -> Tuple[list[Expense], int]:
    """
    报销单列表：一律只返回当前用户自己的报销单。
    特权角色查看他人单据走审批中心（详情接口由 _check_read_permission 控制）。
    """
    query = db.query(Expense).filter(Expense.user_id == user.id)
    if status:
        query = query.filter(Expense.status == status)
    if expense_type:
        query = query.filter(Expense.expense_type == expense_type)

    total = query.count()
    items = (
        query.order_by(Expense.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def list_all_expenses(
    db: Session,
    user: User,
    page: int = 1,
    page_size: int = 10,
    status: Optional[ExpenseStatus] = None,
    expense_type: Optional[ExpenseType] = None,
) -> Tuple[list[Expense], int]:
    """
    全部报销单列表（监管视角，路由层已限制 manager/finance/admin）：
    manager 只看本部门；finance/admin 看全部。
    申请人姓名/部门由Expense模型上的applicant_* property提供（joinedload已避免N+1）。
    """
    query = db.query(Expense).options(joinedload(Expense.user))
    if user.role == UserRole.MANAGER:
        query = query.join(User, Expense.user_id == User.id).filter(
            (Expense.user_id == user.id) | (User.department == user.department)
        )
    if status:
        query = query.filter(Expense.status == status)
    if expense_type:
        query = query.filter(Expense.expense_type == expense_type)

    total = query.count()
    items = (
        query.order_by(Expense.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_expense(db: Session, expense_id: int, user: User) -> Expense:
    """报销单详情（含读取权限校验）"""
    expense = _get_or_404(db, expense_id)
    _check_read_permission(expense, user)
    return expense


def update_expense(db: Session, expense_id: int, user: User, data: ExpenseUpdate) -> Expense:
    """更新报销单（仅草稿/被驳回状态可编辑，仅本人）"""
    expense = _get_or_404(db, expense_id)
    if expense.user_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能编辑自己的报销单")
    if not expense.is_editable:
        raise HTTPException(status_code=400, detail=f"当前状态 {expense.status.value} 不可编辑")

    if data.items is not None:
        _validate_categories(db, [item.category_id for item in data.items])
        expense.items.clear()  # cascade delete-orphan
        db.flush()
        total = Decimal("0")
        for item in data.items:
            db.add(ExpenseItem(
                expense_id=expense.id,
                category_id=item.category_id,
                description=item.description,
                amount=item.amount,
                expense_date=item.expense_date,
                invoice_no=item.invoice_no,
                invoice_url=item.invoice_url,
            ))
            total += item.amount
        expense.total_amount = total

    for field in ("title", "expense_type", "description", "remark"):
        value = getattr(data, field)
        if value is not None:
            setattr(expense, field, value)

    db.commit()
    db.refresh(expense)
    return expense


def delete_expense(db: Session, expense_id: int, user: User) -> None:
    """删除报销单（仅草稿/被驳回状态，仅本人）"""
    expense = _get_or_404(db, expense_id)
    if expense.user_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能删除自己的报销单")
    if not expense.is_editable:
        raise HTTPException(status_code=400, detail=f"当前状态 {expense.status.value} 不可删除")
    db.delete(expense)
    db.commit()


def submit_expense(db: Session, expense_id: int, user: User) -> Expense:
    """
    提交报销单：DRAFT/REJECTED → SUBMITTED
    写入SUBMIT审批记录；AI审核触发由端点层处理（阶段5接入工作流）
    """
    expense = _get_or_404(db, expense_id)
    if expense.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能提交自己的报销单")
    if expense.status not in (ExpenseStatus.DRAFT, ExpenseStatus.REJECTED):
        raise HTTPException(status_code=400, detail=f"当前状态 {expense.status.value} 不可提交")

    expense.status = ExpenseStatus.SUBMITTED
    expense.submitted_at = utc_now()
    expense.rejection_reason = None  # 清除上次驳回原因
    db.add(Approval(
        expense_id=expense.id,
        approver_id=user.id,
        approver_name=user.full_name or user.username,
        action=ApprovalAction.SUBMIT,
        comment="提交报销单",
    ))
    db.commit()
    db.refresh(expense)
    logger.info(f"报销单 {expense.expense_no} 已提交")
    return expense


def cancel_expense(db: Session, expense_id: int, user: User) -> Expense:
    """取消报销单（仅草稿/已提交且未进入审批时）"""
    expense = _get_or_404(db, expense_id)
    if expense.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能取消自己的报销单")
    if expense.status not in (ExpenseStatus.DRAFT, ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        raise HTTPException(status_code=400, detail=f"当前状态 {expense.status.value} 不可取消")
    expense.status = ExpenseStatus.CANCELLED
    db.commit()
    db.refresh(expense)
    return expense


def pay_expense(db: Session, expense_id: int, user: User) -> Expense:
    """
    财务打款登记：APPROVED → PAID
    只改状态+记时间，真实转账发生在系统外（网银/财务系统），
    此接口是财务转完钱回来点的"登记"按钮
    """
    if not user.has_permission("pay"):
        raise HTTPException(status_code=403, detail="仅财务可执行打款登记")
    expense = _get_or_404(db, expense_id)
    if expense.status != ExpenseStatus.APPROVED:
        raise HTTPException(status_code=400, detail=f"当前状态 {expense.status.value} 不可打款（仅已通过的单）")

    expense.status = ExpenseStatus.PAID
    expense.paid_at = utc_now()
    db.commit()
    db.refresh(expense)
    # 打款完成通知申请人（失败不影响登记结果）
    try:
        notify_payment(db, expense)
    except Exception as e:
        logger.warning(f"打款通知失败（不影响主流程）: {e}")
    logger.info(f"财务 {user.username} 打款登记 报销单 {expense.expense_no}")
    return expense


def build_snapshot(db: Session, expense_id: int) -> dict:
    """
    构造报销单快照（供AI Agent工作流使用）：
    单据信息 + 明细 + 类别名/限额 + 申请人信息 + 申请人近90天报销统计
    """
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail=f"报销单 {expense_id} 不存在")

    owner = expense.user
    since = date.today() - timedelta(days=90)
    recent = (
        db.query(func.count(Expense.id), func.coalesce(func.sum(Expense.total_amount), 0))
        .filter(
            Expense.user_id == expense.user_id,
            Expense.created_at >= since,
            Expense.id != expense.id,
        )
        .one()
    )

    items = []
    for it in expense.items:
        cat = it.category
        items.append({
            "id": it.id,
            "category_id": it.category_id,
            "category_name": cat.name if cat else None,
            "category_max_amount": float(cat.max_amount) if cat and cat.max_amount else None,
            "description": it.description,
            "amount": float(it.amount),
            "expense_date": it.expense_date.isoformat() if it.expense_date else None,
            "invoice_no": it.invoice_no,
            "invoice_url": it.invoice_url,
        })

    return {
        "expense": {
            "id": expense.id,
            "expense_no": expense.expense_no,
            "title": expense.title,
            "expense_type": expense.expense_type.value if expense.expense_type else None,
            "total_amount": float(expense.total_amount),
            "currency": expense.currency,
            "expense_date": expense.expense_date.isoformat() if expense.expense_date else None,
            "description": expense.description,
            "remark": expense.remark,
            "status": expense.status.value if expense.status else None,
        },
        "items": items,
        "applicant": {
            "id": owner.id if owner else None,
            "username": owner.username if owner else None,
            "department": owner.department if owner else None,
            "position": owner.position if owner else None,
            "recent_90d_count": int(recent[0]),
            "recent_90d_total": float(recent[1]),
        },
    }
