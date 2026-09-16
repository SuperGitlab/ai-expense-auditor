"""
报销数据模型
定义报销单、报销项目、费用类别等表结构
"""
from sqlalchemy import Column, BigInteger, Integer, String, Boolean, Numeric, Date, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.models.base import Base


class ExpenseStatus(str, enum.Enum):
    """报销状态枚举"""
    DRAFT = "draft"               # 草稿
    SUBMITTED = "submitted"       # 已提交
    PENDING = "pending"           # 审核中
    MANAGER_APPROVED = "manager_approved"  # 经理已初审，待财务终审
    APPROVED = "approved"         # 已通过
    REJECTED = "rejected"         # 已拒绝
    PAID = "paid"                 # 已支付
    CANCELLED = "cancelled"       # 已取消


class ExpenseType(str, enum.Enum):
    """报销类型枚举"""
    TRAVEL = "travel"             # 差旅费
    MEAL = "meal"                 # 餐饮费
    TRANSPORTATION = "transportation"  # 交通费
    ACCOMMODATION = "accommodation"    # 住宿费
    OFFICE = "office"             # 办公费
    OTHER = "other"               # 其他


class Expense(Base):
    """
    报销单模型表
    """

    __tablename__ = "expenses"

    # 主键
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # 基本信息
    expense_no = Column(String(50), unique=True, index=True, nullable=False, comment="报销单号")
    title = Column(String(200), nullable=False, comment="报销标题")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="申请人ID")

    # 报销详情
    expense_type = Column(Enum(ExpenseType), default=ExpenseType.OTHER, nullable=False, comment="报销类型")
    total_amount = Column(Numeric(12, 2), nullable=False, default=0, comment="报销总金额")
    currency = Column(String(3), nullable=False, default="CNY", comment="币种")
    expense_date = Column(Date, comment="费用发生日期")
    description = Column(Text, comment="报销说明")
    remark = Column(String(500), comment="备注")

    # 审核状态
    status = Column(Enum(ExpenseStatus), default=ExpenseStatus.DRAFT, nullable=False, index=True, comment="报销状态")
    rejection_reason = Column(Text, comment="驳回原因")

    # AI审核结果
    risk_level = Column(String(20), comment="AI风险等级: low/medium/high")
    risk_score = Column(Numeric(5, 2), comment="AI风险分数 0-100")
    ai_review_result = Column(Text, comment="AI审核结果说明")

    # 时间戳
    submitted_at = Column(DateTime(timezone=True), comment="提交时间")
    approved_at = Column(DateTime(timezone=True), comment="审批通过时间")
    paid_at = Column(DateTime(timezone=True), comment="打款时间（财务在系统外转账后回来登记）")
    # server_default：INSERT没提供该列时由数据库时钟填默认值（MySQL方言翻译为DEFAULT CURRENT_TIMESTAMP）；
    # 好处是绕过ORM的写入（手工SQL/修复脚本/其他服务直连）同样有创建时间，时钟以数据库为准
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), comment="更新时间")

    # 关联关系
    user = relationship("User", back_populates="expenses")
    items = relationship("ExpenseItem", back_populates="expense", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="expense", cascade="all, delete-orphan")
    node_runs = relationship("AgentNodeRun", back_populates="expense", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Expense(id={self.id}, expense_no={self.expense_no}, status={self.status})>"

    @property
    def is_editable(self) -> bool:
        """草稿或已驳回状态下可编辑"""
        return self.status in (ExpenseStatus.DRAFT, ExpenseStatus.REJECTED)

    @property
    def applicant_name(self) -> str:
        """申请人姓名（审批中心列表展示用，冗余字段避免前端二次查询）"""
        if self.user:
            return self.user.full_name or self.user.username
        return ""

    @property
    def applicant_department(self) -> str:
        """申请人部门"""
        if self.user:
            return self.user.department or ""
        return ""


class ExpenseItem(Base):
    """报销项目表模型"""

    __tablename__ = "expense_items"

    # 主键
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # 关联报销单
    expense_id = Column(BigInteger, ForeignKey("expenses.id"), nullable=False, index=True, comment="报销单ID")

    # 关联费用类别
    category_id = Column(BigInteger, ForeignKey("categories.id"), comment="费用类别ID")

    # 项目信息
    description = Column(String(500), nullable=False, comment="费用说明")
    amount = Column(Numeric(12, 2), nullable=False, comment="金额")

    # 日期信息
    expense_date = Column(Date, nullable=False, comment="费用发生日期")

    # 发票信息
    invoice_no = Column(String(100), comment="发票号码")
    invoice_url = Column(String(500), comment="发票文件URL")
    invoice_verified = Column(Boolean, default=False, comment="发票是否已验证")

    # 时间戳
    # server_default：INSERT没提供该列时由数据库时钟填默认值（MySQL生成DEFAULT CURRENT_TIMESTAMP），
    # 绕过ORM的写入（手工SQL/脚本直连）同样有值——详见Expense.created_at处的完整说明
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关联关系
    expense = relationship("Expense", back_populates="items")
    category = relationship("Category", back_populates="items")

    def __repr__(self):
        return f"<ExpenseItem(id={self.id}, amount={self.amount})>"

    


class Category(Base):
    """费用类别表模型"""

    __tablename__ = "categories"

    # 主键
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # 类别信息
    name = Column(String(100), nullable=False, comment="类别名称")
    code = Column(String(50), unique=True, nullable=False, comment="类别代码")
    max_amount = Column(Numeric(12,2), comment="单次最高金额")
    description = Column(Text, comment="类别描述")

    # 状态
    is_active = Column(Boolean, default=True, comment="是否启用")

    # 时间戳
    # server_default：INSERT没提供该列时由数据库时钟填默认值（MySQL生成DEFAULT CURRENT_TIMESTAMP），
    # 绕过ORM的写入（手工SQL/脚本直连）同样有值——详见Expense.created_at处的完整说明
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关联关系
    items = relationship("ExpenseItem", back_populates="category")

    def __repr__(self):
        return f"<Category(id={self.id}, name={self.name})>"