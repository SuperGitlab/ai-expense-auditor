"""
报表接口
汇总统计、月度趋势、分类占比（finance/admin）
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DBSession, require_roles
from app.models import User, UserRole
from app.services import report_service

router = APIRouter(prefix="/api/reports", tags=["报表统计"])

# finance/admin可访问
ReportUser = Annotated[User, Depends(require_roles(UserRole.FINANCE, UserRole.ADMIN))]


@router.get("/summary")
def summary(db: DBSession, current_user: ReportUser):
    """总览统计：总数/各状态/总金额/平均风险分/本月数"""
    return report_service.get_summary(db)


@router.get("/trends")
def trends(
    db: DBSession,
    current_user: ReportUser,
    months: int = Query(6, ge=1, le=24, description="统计月数"),
):
    """月度趋势：提交量与金额"""
    return report_service.get_trends(db, months)


@router.get("/by-category")
def by_category(db: DBSession, current_user: ReportUser):
    """分类占比：各类别报销额与笔数"""
    return report_service.get_by_category(db)
