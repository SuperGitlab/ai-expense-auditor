"""
数据库查询工具
供Agent使用的辅助查询（重复发票检测）
"""
import logging

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
