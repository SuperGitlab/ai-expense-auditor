"""
用户数据模式
定义用户注册、登录、信息相关的 Pydantic 模式
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import UserRole


class UserBase(BaseModel):
    """用户基础模式"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: str = Field(..., max_length=100, description="邮箱")
    full_name: Optional[str] = Field(None, max_length=100, description="姓名")
    phone: Optional[str] = Field(None, max_length=20, description="电话")
    department: Optional[str] = Field(None, max_length=100, description="部门")
    position: Optional[str] = Field(None, max_length=100, description="职位")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """简单邮箱格式校验（避免引入email-validator额外依赖）"""
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("邮箱格式不正确")
        return v


class UserCreate(UserBase):
    """用户创建（注册）模式"""
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    role: UserRole = Field(UserRole.EMPLOYEE, description="角色")


class UserUpdate(BaseModel):
    """用户信息更新模式"""
    full_name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    department: Optional[str] = Field(None, max_length=100)
    position: Optional[str] = Field(None, max_length=100)


class UserRoleUpdate(BaseModel):
    """用户角色更新模式（admin用）"""
    role: UserRole


class UserStatusUpdate(BaseModel):
    """用户启用/禁用模式（admin用）"""
    is_active: bool


class UserResponse(UserBase):
    """用户响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: UserRole
    is_active: bool
    is_superuser: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


class LoginRequest(BaseModel):
    """登录请求模式（JSON方式，前端使用）"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class Token(BaseModel):
    """登录令牌响应模式"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
