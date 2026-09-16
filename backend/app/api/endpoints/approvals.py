"""
审批接口
待审列表、审批历史、人工审批决策
"""
from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DBSession
from app.schemas.approval import (ApprovalDecisionRequest,
                                  ApprovalListResponse, ApprovalResponse,
                                  PendingExpenseItem)
from app.services import approval_service, expense_service

router = APIRouter(prefix="/api/approvals", tags=["审批中心"])


@router.get("/pending", response_model=list[PendingExpenseItem])
def list_pending(db: DBSession, current_user: CurrentUser):
    """待审批列表（finance/manager）"""
    return approval_service.list_pending(db, current_user)


@router.get("/{expense_id}/history", response_model=ApprovalListResponse)
def get_history(expense_id: int, db: DBSession, current_user: CurrentUser):
    """报销单审批历史（含AI审核记录，需有读取权限）"""
    # 借用报销单读取权限校验
    expense_service.get_expense(db, expense_id, current_user)
    items = approval_service.get_history(db, expense_id)
    return ApprovalListResponse(items=items, total=len(items))


@router.post("/decide", response_model=PendingExpenseItem)
def decide(body: ApprovalDecisionRequest, db: DBSession, current_user: CurrentUser):
    """人工审批：通过/驳回（finance/manager）"""
    expense = approval_service.decide(db, current_user, body)
    return expense


@router.post("/takeover", response_model=PendingExpenseItem)
def takeover(body: ApprovalDecisionRequest, db: DBSession, current_user: CurrentUser):
    """
    人工接管（人审优先）：AI执行中(SUBMITTED)/待初审(PENDING)/待终审(MANAGER_APPROVED)
    的单据，manager(本部门)/finance/admin 可随时直接批准/驳回；
    AI之后算出的结论只留档不生效（workflow落库守卫）；驳回必须填写意见
    """
    expense = approval_service.decide(db, current_user, body, takeover=True)
    return expense
