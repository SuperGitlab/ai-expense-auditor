"""
报销接口
报销单CRUD、提交、取消
"""
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DBSession, require_roles
from app.config import settings
from app.models import (Expense, ExpenseStatus, ExpenseType, User,
                        UserRole)
from app.schemas.expense import (ExpenseCreate, ExpenseListResponse,
                                 ExpenseResponse, ExpenseUpdate)
from app.services import expense_service
from app.tasks import celery_app
from app.tasks.review import run_ai_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/expenses", tags=["报销管理"])


def _ensure_review_queue() -> None:
    """提交前探活AI审核队列（broker=Redis）。

    不可用直接503、单据保持草稿——不降级为进程内执行（用户明确要求显式报错）。
    只探broker可达；worker未启动时任务暂存Redis等消费，不算错误。
    """
    conn = celery_app.connection()
    try:
        conn.connect()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"AI审核队列不可用：请先启动 Redis 与 Celery worker 后再提交（{type(e).__name__}）",
        )
    finally:
        try:
            conn.close()
        except Exception as e:
            logger.debug("关闭broker连接失败（忽略）: %s", e)


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(data: ExpenseCreate, db: DBSession, current_user: CurrentUser):
    """创建报销单（草稿状态）"""
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


@router.post("/{expense_id}/submit", response_model=ExpenseResponse)
async def submit_expense(
    expense_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    提交报销单进入审核流程（立即返回）
    AI审核放Celery worker跑：串在请求里要等3次LLM调用（约2-3分钟），前端会一直转圈。
    响应返回时单据状态为SUBMITTED，后台审核完成后流转为approved/rejected/pending。
    队列不可用时提交直接503（单据保持草稿），不做进程内降级。
    """
    if settings.AGENT_REVIEW_ON_SUBMIT:
        _ensure_review_queue()  # 探活放提交动作前：失败则单据原样留在草稿

    expense = expense_service.submit_expense(db, expense_id, current_user)

    if settings.AGENT_REVIEW_ON_SUBMIT:
        run_ai_review.delay(expense_id)  # Celery队列：削峰/持久化/多worker

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
