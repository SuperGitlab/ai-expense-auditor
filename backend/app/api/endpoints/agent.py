"""
AI审核接口
手动触发AI审核、查询工作流结构、节点执行轨迹
"""
import logging

from fastapi import APIRouter, HTTPException

from app.agents.workflow import workflow
from app.api.deps import CurrentUser, DBSession
from app.config import settings
from app.models import AgentNodeRun, ExpenseStatus, UserRole
from app.schemas.agent import AIReviewRequest, AIReviewResponse
from app.services.expense_service import get_expense

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["AI审核"])

# 节点顺序与中文名（画布固定结构，未启动节点也按此顺序补齐）
_NODE_LABELS = {
    "document": "单据解析",
    "rule": "规则校验",
    "rag": "RAG检索",
    "risk": "风险评估",
    "decision": "终审裁决",
}


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


@router.get("/executions/{expense_id}")
def get_executions(expense_id: int, db: DBSession, current_user: CurrentUser):
    """
    节点执行轨迹（工作流画布数据源，3s轮询）
    权限同报销单读取：本人 / finance / admin / manager(本部门)
    固定返回5节点全量：未启动的节点补 status=pending，画布结构稳定
    """
    expense = get_expense(db, expense_id, current_user)  # 404/403

    runs = db.query(AgentNodeRun).filter(AgentNodeRun.expense_id == expense_id).all()
    by_node = {r.node: r for r in runs}
    nodes = []
    for name in _NODE_LABELS:
        run = by_node.get(name)
        nodes.append({
            "node": name,
            "label": _NODE_LABELS[name],
            "status": run.status if run else "pending",
            "started_at": run.started_at if run else None,
            "finished_at": run.finished_at if run else None,
            "detail": run.detail if run else None,
            "error": run.error if run else None,
        })
    return {"nodes": nodes, "expense_status": expense.status.value}
