"""
报销接口
报销单CRUD、提交、取消
"""
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.api.deps import CurrentUser, DBSession, require_roles
from app.config import settings
from app.models import (Expense, ExpenseStatus, ExpenseType, User,
                        UserRole)
from app.schemas.expense import (ExpenseCreate, ExpenseListResponse,
                                 ExpenseResponse, ExpenseUpdate)
from app.services import expense_service

router = APIRouter(prefix="/api/expenses", tags=["报销管理"])


# @router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
# def create_expense(data: ExpenseCreate, db: DBSession, current_user: CurrentUser):
#     """创建报销单（草稿状态）"""
#     return expense_service.create_expense(db, current_user, data)

@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(data: ExpenseCreate, db: DBSession, current_user: CurrentUser):
    """创建报销状态"""
    return expense_service.create_expense(db, current_user, data)


@router.get("", response_model=ExpenseListResponse)
def list_expenses(
    db: DBSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: Optional[ExpenseStatus] = Query(None, alias="status", description="按状态过滤"),
    expense_type: Optional[ExpenseType] = Query(None, description="按类型过滤"),
):
    """报销单列表（只返回当前用户自己的报销单）"""
    items, total = expense_service.list_expenses(
        db, current_user, page, page_size, status_filter, expense_type
    )
    from app.utils.helpers import paginate
    return paginate(items, total, page, page_size)


# 注意：/all 必须声明在 /{expense_id} 之前，否则 "all" 会被当成路径参数解析成422
@router.get("/all", response_model=ExpenseListResponse)
def list_all_expenses(
    db: DBSession,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.MANAGER, UserRole.FINANCE, UserRole.ADMIN))
    ],
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: Optional[ExpenseStatus] = Query(None, alias="status", description="按状态过滤"),
    expense_type: Optional[ExpenseType] = Query(None, description="按类型过滤"),
):
    """全部报销单（监管视角：manager看本部门，finance/admin看全部；employee无权访问）"""
    items, total = expense_service.list_all_expenses(
        db, current_user, page, page_size, status_filter, expense_type
    )
    from app.utils.helpers import paginate
    return paginate(items, total, page, page_size)


@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_expense(expense_id: int, db: DBSession, current_user: CurrentUser):
    """报销单详情"""
    return expense_service.get_expense(db, expense_id, current_user)


@router.put("/{expense_id}", response_model=ExpenseResponse)
def update_expense(expense_id: int, data: ExpenseUpdate, db: DBSession, current_user: CurrentUser):
    """更新报销单（仅草稿/被驳回，仅本人）"""
    return expense_service.update_expense(db, expense_id, current_user, data)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int, db: DBSession, current_user: CurrentUser):
    """删除报销单（仅草稿/被驳回，仅本人）"""
    expense_service.delete_expense(db, expense_id, current_user)


async def run_review_in_background(expense_id: int) -> None:
    """
    后台执行AI审核（BackgroundTasks：响应发出后才跑）
    必须自开session——请求里的db随请求结束已关闭，传进来必炸
    """
    from app.agents.workflow import workflow as review_workflow
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await review_workflow.run(db, expense_id)
    except Exception as e:
        # AI审核失败：保守转人工，单据留在PENDING状态，不影响提交本身
        logger = logging.getLogger(__name__)
        logger.error(f"后台AI审核失败（转人工）: {e}")
        db.rollback()
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if expense:
            expense.status = ExpenseStatus.PENDING
            db.commit()
    finally:
        db.close()


@router.post("/{expense_id}/submit", response_model=ExpenseResponse)
async def submit_expense(
    expense_id: int,
    background_tasks: BackgroundTasks,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    提交报销单进入审核流程（立即返回）
    AI审核放后台任务跑：串在请求里要等3次LLM调用（约2-3分钟），前端会一直转圈。
    响应返回时单据状态为SUBMITTED，后台审核完成后流转为approved/rejected/pending。
    """
    expense = expense_service.submit_expense(db, expense_id, current_user)

    if settings.AGENT_REVIEW_ON_SUBMIT:
        background_tasks.add_task(run_review_in_background, expense_id)

    return expense


@router.post("/{expense_id}/cancel", response_model=ExpenseResponse)
def cancel_expense(expense_id: int, db: DBSession, current_user: CurrentUser):
    """取消报销单"""
    return expense_service.cancel_expense(db, expense_id, current_user)


@router.post("/{expense_id}/pay", response_model=ExpenseResponse)
def pay_expense(expense_id: int, db: DBSession, current_user: CurrentUser):
    """
    财务打款登记（approved → paid）
    真实转账在系统外完成，此接口只登记状态与时间
    """
    return expense_service.pay_expense(db, expense_id, current_user)
