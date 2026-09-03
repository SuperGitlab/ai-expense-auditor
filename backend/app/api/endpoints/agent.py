"""
AI审核接口
手动触发AI审核、查询工作流结构
"""
import logging

from fastapi import APIRouter, HTTPException

from app.agents.workflow import workflow
from app.api.deps import CurrentUser, DBSession
from app.config import settings
from app.models import ExpenseStatus, UserRole
from app.schemas.agent import AIReviewRequest, AIReviewResponse
from app.services.expense_service import get_expense

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["AI审核"])


@router.post("/review", response_model=AIReviewResponse)
async def review_expense(body: AIReviewRequest, db: DBSession, current_user: CurrentUser):
    """
    触发AI审核工作流（权限：本人单据 / admin / finance）
    仅 SUBMITTED / PENDING 状态的报销单可审核
    """
    # 读取权限复用报销单校验（404/403）
    expense = get_expense(db, body.expense_id, current_user)

    if current_user.role not in (UserRole.ADMIN, UserRole.FINANCE) and expense.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能触发本人报销单的AI审核")

    if expense.status not in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {expense.status.value} 不可审核（仅已提交/待审核状态）",
        )

    try:
        result = await workflow.run(db, body.expense_id)
        return result
    except Exception as e:
        logger.exception("AI审核执行失败")
        raise HTTPException(status_code=500, detail=f"AI审核执行失败: {e}")


@router.get("/workflow")
def workflow_info(current_user: CurrentUser):
    """工作流结构信息（前端可视化用）"""
    return {
        "nodes": ["document", "rule", "rag", "risk", "decision"],
        "edges": [
            {"from": "START", "to": "document"},
            {"from": "document", "to": "rule"},
            {"from": "document", "to": "rag"},
            {"from": "rule", "to": "risk"},
            {"from": "rag", "to": "risk"},
            {"from": "risk", "to": "decision"},
            {"from": "decision", "to": "END"},
        ],
        "parallel": ["rule", "rag"],
        "auto_review_on_submit": settings.AGENT_REVIEW_ON_SUBMIT,
        "risk_thresholds": {
            "low_max": settings.RISK_LOW_MAX,
            "high_min": settings.RISK_HIGH_MIN,
        },
    }
