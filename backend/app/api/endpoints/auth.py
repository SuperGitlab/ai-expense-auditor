"""
认证接口
注册、登录（表单/JSON两种方式）、当前用户信息
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DBSession
from app.schemas.user import LoginRequest, Token, UserCreate, UserResponse
from app.services.auth_service import (authenticate_user, create_access_token,
                                       register_user)

router = APIRouter(prefix="/api/auth", tags=["认证"])


# @router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
# def register(user_in: UserCreate, db: DBSession):
#     """用户注册"""
#     try:
#         return register_user(db, user_in)
#     except ValueError as e:
#         raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: DBSession):
    """用户注册"""
    try:
        return register_user(db, user_in)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DBSession):
    """
    登录（表单方式，Swagger右上角Authorize按钮使用此端点）
    """
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user), user=UserResponse.model_validate(user))


# @router.post("/login-json", response_model=Token)
# def login_json(login_in: LoginRequest, db: DBSession):
#     """登录（JSON方式，前端使用）"""
#     user = authenticate_user(db, login_in.username, login_in.password)
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="用户名或密码错误",
#         )
#     return Token(access_token=create_access_token(user), user=UserResponse.model_validate(user))

@router.post("/login-json", response_model=Token)
def login_json(login_in: LoginRequest, db: DBSession):
    """登录（JSON方式，前端使用）"""
    user = authenticate_user(db, login_in.username, login_in.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    return Token(access_token=create_access_token(user), user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def read_me(current_user: CurrentUser):
    """获取当前登录用户信息"""
    return current_user
