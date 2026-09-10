"""
用户管理接口
用户列表、详情、角色与状态管理（admin）
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import DBSession, require_roles
from app.models.user import User, UserRole
from app.schemas.user import UserResponse, UserRoleUpdate, UserStatusUpdate

router = APIRouter(prefix="/api/users", tags=["用户管理"])


def _get_user_or_404(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    return user


@router.get("", response_model=list[UserResponse])
def list_users(
    db: DBSession,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[UserRole] = Query(None, description="按角色过滤"),
):
    """用户列表（admin，分页+角色过滤）"""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    return (
        query.order_by(User.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: DBSession,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
):
    """用户详情（admin）"""
    return _get_user_or_404(db, user_id)


@router.patch("/{user_id}/role", response_model=UserResponse)
def update_role(
    user_id: int,
    body: UserRoleUpdate,
    db: DBSession,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
):
    """修改用户角色（admin）"""
    user = _get_user_or_404(db, user_id)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    user.role = body.role
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserResponse)
def update_status(
    user_id: int,
    body: UserStatusUpdate,
    db: DBSession,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
):
    """启用/禁用用户（admin）"""
    user = _get_user_or_404(db, user_id)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的状态（避免误禁用自己）")
    user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user
