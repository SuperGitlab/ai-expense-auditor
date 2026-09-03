"""
数据库查询工具
供Agent使用的辅助查询（重复发票检测、申请人报销统计）
"""
import logging
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseItem, ExpenseStatus

logger = logging.getLogger(__name__)


def find_duplicate_invoice(
    db: Session, invoice_no: str, exclude_expense_id: int | None = None
) -> dict | None:
    """
    检测发票号是否已被其他报销单使用

    Returns:
        dict: {invoice_no, expense_id, expense_no, status}；无重复返回None
    """
    if not invoice_no:
        return None
    query = (
        db.query(ExpenseItem)
        .filter(ExpenseItem.invoice_no == invoice_no)
        .filter(ExpenseItem.expense_id != exclude_expense_id)
        .join(Expense, ExpenseItem.expense_id == Expense.id)
        .filter(Expense.status != ExpenseStatus.CANCELLED)
        .first()
    )
    if not query:
        return None
    return {
        "invoice_no": invoice_no,
        "expense_id": query.expense_id,
        "description": query.description,
    }


def get_user_recent_stats(db: Session, user_id: int, days: int = 90) -> dict:
    """
    申请人近N天报销统计（高频报销是风险信号）

    Returns:
        dict: {count, total_amount, avg_amount}
    """
    since = date.today() - timedelta(days=days)
    result = (
        db.query(
            func.count(Expense.id),
            func.coalesce(func.sum(Expense.total_amount), 0),
        )
        .filter(
            Expense.user_id == user_id,
            Expense.created_at >= since,
            Expense.status != ExpenseStatus.CANCELLED,
        )
        .one()
    )
    count, total = int(result[0]), float(result[1])
    return {
        "count": count,
        "total_amount": total,
        "avg_amount": round(total / count, 2) if count else 0.0,
    }
