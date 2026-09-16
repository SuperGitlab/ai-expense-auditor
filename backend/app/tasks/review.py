"""
AI审核Celery任务
"""
import asyncio
import logging

from app.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="review.run_ai_review")
def run_ai_review(expense_id: int) -> str:
    """
    执行AI审核工作流（提交链路唯一执行方，无进程内降级）：
    自开session（worker进程独立于请求生命周期）、失败保守转PENDING人工。
    workflow.run是async，worker里用asyncio.run驱动；返回字符串作为任务结果便于观测。
    """
    from app.agents.workflow import workflow as review_workflow
    from app.database import SessionLocal
    from app.models import Expense, ExpenseStatus

    db = SessionLocal()
    try:
        asyncio.run(review_workflow.run(db, expense_id))
        return f"expense#{expense_id} reviewed"
    except Exception as e:
        # AI审核失败：保守转人工，单据留在PENDING状态，不影响提交本身
        # 人审优先：人工已接管（状态离开SUBMITTED）则不再改状态
        logger.error(f"后台AI审核失败（转人工）: {e}")
        db.rollback()
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if expense and expense.status == ExpenseStatus.SUBMITTED:
            expense.status = ExpenseStatus.PENDING
            db.commit()
        return f"expense#{expense_id} fallback_to_pending: {e}"
    finally:
        db.close()
