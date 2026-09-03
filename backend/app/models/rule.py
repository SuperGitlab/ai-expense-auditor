"""
规则数据模型
规则引擎的持久化规则定义，供规则校验Agent加载执行
"""
import enum

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Enum,
                        ForeignKey, Integer, String, Text)
from sqlalchemy.sql import func

from app.models.base import Base


class RuleType(str, enum.Enum):
    """规则类型枚举"""
    AMOUNT_LIMIT = "amount_limit"            # 金额限制
    INVOICE_REQUIRED = "invoice_required"    # 发票要求
    DATE_LIMIT = "date_limit"                # 日期限制（超期）
    DUPLICATE_INVOICE = "duplicate_invoice"  # 重复发票
    CATEGORY_RESTRICT = "category_restrict"  # 类别限制
    CUSTOM = "custom"                        # 自定义


class RuleSeverity(str, enum.Enum):
    """规则严重级别枚举"""
    BLOCK = "block"    # 命中即自动驳回
    WARN = "warn"      # 命中计入风险分
    REVIEW = "review"  # 命中强制转人工审批


class RuleOperator(str, enum.Enum):
    """比较操作符枚举"""
    GT = "gt"                    # 大于
    LT = "lt"                    # 小于
    GTE = "gte"                  # 大于等于
    LTE = "lte"                  # 小于等于
    EQ = "eq"                    # 等于
    IN = "in"                    # 在集合内（threshold逗号分隔）
    EXISTS = "exists"            # 字段存在/非空
    NOT_EXISTS = "not_exists"    # 字段缺失/为空


class Rule(Base):
    """
    审核规则表模型
    threshold统一用字符串存储，规则引擎按field类型转型比较
    """

    __tablename__ = "rules"

    # 主键
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # 规则定义
    name = Column(String(100), nullable=False, comment="规则名称")
    code = Column(String(50), unique=True, nullable=False, index=True, comment="规则代码")
    rule_type = Column(Enum(RuleType), default=RuleType.CUSTOM, nullable=False, comment="规则类型")

    # 作用范围（category_id为空表示适用于所有类别）
    category_id = Column(BigInteger, ForeignKey("categories.id"), nullable=True, comment="限定费用类别ID")

    # 判定条件
    field_name = Column(String(50), nullable=False, comment="作用字段: amount/expense_date/invoice_no/description")
    operator = Column(Enum(RuleOperator), nullable=False, comment="比较操作符")
    threshold = Column(String(200), comment="阈值（字符串存储，引擎内转型）")

    # 处理策略
    severity = Column(Enum(RuleSeverity), default=RuleSeverity.WARN, nullable=False, comment="严重级别")
    risk_points = Column(Integer, default=10, comment="命中时计入的风险分")

    # 说明与状态
    description = Column(String(500), comment="规则说明")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<Rule(id={self.id}, code={self.code}, severity={self.severity})>"
