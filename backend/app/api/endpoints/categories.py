"""
费用类别接口
提交报销表单的类别下拉数据（登录即可读）；管理增删改（admin）
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DBSession, require_roles
from app.models import Category, ExpenseItem, Rule, User, UserRole
from app.schemas.category import (
    CategoryCreate,
    CategoryDeleteResult,
    CategoryResponse,
    CategoryUpdate,
)

router = APIRouter(prefix="/api/categories", tags=["费用类别"])

# 管理员依赖
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=list[CategoryResponse])
def list_categories(db: DBSession, current_user: CurrentUser, include_inactive: bool = False):
    """费用类别列表（默认仅启用；include_inactive=true 需 admin，管理页用）"""
    query = db.query(Category)
    if include_inactive:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="仅管理员可查看停用类别")
    else:
        query = query.filter(Category.is_active == True)  # noqa: E712
    return query.order_by(Category.id).all()


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(data: CategoryCreate, db: DBSession, current_user: AdminUser):
    """创建费用类别（admin）"""
    if db.query(Category).filter(Category.code == data.code).first():
        raise HTTPException(status_code=409, detail=f"类别代码 {data.code} 已存在")
    category = Category(**data.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(category_id: int, data: CategoryUpdate, db: DBSession, current_user: AdminUser):
    """更新费用类别（admin；code 创建后不可改）"""
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail=f"类别 {category_id} 不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", response_model=CategoryDeleteResult)
def delete_category(category_id: int, db: DBSession, current_user: AdminUser):
    """删除费用类别（admin）

    绑定该类别的规则将被停用并解绑（规则行保留、可再启用）；
    存在历史报销明细时外键会挡住物理删除，转为停用（历史单据不受影响）。
    """
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail=f"类别 {category_id} 不存在")

    hidden_rules = (
        db.query(Rule)
        .filter(Rule.category_id == category_id)
        .update({"is_active": False, "category_id": None}, synchronize_session=False)
    )
    has_history = (
        db.query(ExpenseItem.id).filter(ExpenseItem.category_id == category_id).first() is not None
    )
    if has_history:
        category.is_active = False
        deleted = False
    else:
        db.delete(category)
        deleted = True
    db.commit()
    return CategoryDeleteResult(deleted=deleted, hidden_rules=hidden_rules, has_history=has_history)
