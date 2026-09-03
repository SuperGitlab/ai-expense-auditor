"""
费用类别接口
提交报销表单的类别下拉数据（登录即可读）
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional

from fastapi import APIRouter

from app.api.deps import CurrentUser, DBSession
from app.models import Category

router = APIRouter(prefix="/api/categories", tags=["费用类别"])


class CategoryResponse(BaseModel):
    """费用类别响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    max_amount: Optional[float] = None
    description: Optional[str] = None


@router.get("", response_model=list[CategoryResponse])
def list_categories(db: DBSession, current_user: CurrentUser):
    """费用类别列表（仅启用的）"""
    return db.query(Category).filter(Category.is_active == True).order_by(Category.id).all()  # noqa: E712
