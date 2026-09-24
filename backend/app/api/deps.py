"""
API公共依赖
数据库会话、当前用户解析、角色校验
"""
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth_service import decode_token

# 令牌提取器：作为依赖使用时，从每个请求的 Authorization: Bearer 头中取出令牌（前端请求也靠它）
# tokenUrl 参数：仅写入接口文档供 Swagger 的 Authorize 按钮指路，处理请求时用不到
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# 类型别名：端点签名中直接使用 Annotated 快捷类型
DBSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBSession,
) -> User:
    """
    解析Bearer令牌并返回当前用户

    Raises:
        HTTPException 401: 令牌无效/过期/用户不存在或被禁用
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录凭证无效或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None or "sub" not in payload:
        raise credentials_exception

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise credentials_exception
    return user


# 当前用户快捷类型：端点签名中 Annotated[User, CurrentUser]
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """
    角色校验依赖工厂：仅允许指定角色访问

    用法: current_user: User = Depends(require_roles(UserRole.ADMIN))
    """
    def checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要角色权限: {', '.join(r.value for r in roles)}",
            )
        return current_user
    return checker
