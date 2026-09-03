import enum

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, func
from sqlalchemy.orm import relationship

from app.models.base import Base


class UserRole(str, enum.Enum):
    """
    用户角色枚举
    """
    ADMIN = "admin"  # 管理员
    FINANCE = "finance"  # 财务人员
    MANAGER = "manager"  # 经理
    EMPLOYEE = "employee"  # 员工


class User(Base):
    """
    用户模型表
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 基本信息
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    email = Column(String(100), unique=True, nullable=False, index=True, comment="邮箱")
    hashed_password = Column(String(255), nullable=False, comment="哈希密码")

    # 个人信息
    full_name = Column(String(100), nullable=True, comment="全名")
    phone = Column(String(20), nullable=True, comment="电话号码")
    department = Column(String(50), nullable=True, comment="部门")
    position = Column(String(50), nullable=True, comment="职位")

    # 角色与权限
    role = Column(Enum(UserRole), default=UserRole.EMPLOYEE, nullable=False, comment="用户角色")

    # 状态
    is_active = Column(Boolean, default=True, nullable=False, comment="是否激活")
    is_superuser = Column(Boolean, default=False, nullable=False, comment="是否为超级用户")

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), comment="更新时间")
    last_login_at = Column(DateTime(timezone=True), comment="最后登录时间")

    # 关联关系（Expense / Approval 模型创建后生效）
    expenses = relationship("Expense", back_populates="user")
    approvals = relationship("Approval", back_populates="approver")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"

    @property
    def is_finance(self) -> bool:
        """是否为财务人员"""
        return self.role == UserRole.FINANCE

    @property
    def is_manager(self) -> bool:
        """是否为经理"""
        return self.role == UserRole.MANAGER

    def has_permission(self, permission: str) -> bool:
        """
        检查用户是否有指定权限

        Args:
            permission: 权限名称

        Returns:
            bool: 是否有权限
        """
        permission_map = {
            "admin": ["all"],
            "finance": ["approve", "reject", "view_all", "export", "pay"],
            "manager": ["approve", "reject", "view_department"],
            "employee": ["submit", "view_own", "edit_own"],
        }

        role_permissions = permission_map.get(self.role.value, [])
        return "all" in role_permissions or permission in role_permissions
