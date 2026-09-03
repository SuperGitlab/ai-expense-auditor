"""
审批数据模型
记录报销单的完整审批历史（提交/AI审核/人工通过/人工驳回）
"""
import enum

from sqlalchemy import (BigInteger, Column, DateTime, Enum, ForeignKey,
                        Integer, Numeric, String, Text)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base


class ApprovalAction(str, enum.Enum):
    """审批动作枚举"""
    SUBMIT = "submit"            # 提交
    AI_REVIEW = "ai_review"      # AI审核
    APPROVE = "approve"          # 人工通过
    REJECT = "reject"            # 人工驳回


class Approval(Base):
    """
    审批记录表模型
    每次状态流转写一行，形成完整审批时间线
    """

    __tablename__ = "approvals"

    # 主键
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # 关联报销单
    expense_id = Column(BigInteger, ForeignKey("expenses.id"), nullable=False, index=True, comment="报销单ID")

    # 审批人（AI审核时为NULL）
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True, comment="审批人ID")
    approver_name = Column(String(50), nullable=False, comment="审批人姓名（AI时为'AI审核系统'）")

    # 审批内容
    action = Column(Enum(ApprovalAction), nullable=False, comment="审批动作")
    comment = Column(Text, comment="审批意见/AI审核说明")

    # AI审核结果字段（仅 action=AI_REVIEW 时记录）
    risk_level = Column(String(20), comment="AI风险等级: low/medium/high")
    risk_score = Column(Numeric(5, 2), comment="AI风险分数 0-100")
    ai_decision = Column(String(30), comment="AI裁决: auto_approve/manual_review/auto_reject")

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="操作时间")

    # 关联关系
    expense = relationship("Expense", back_populates="approvals")
    approver = relationship("User", back_populates="approvals")

    def __repr__(self):
        return f"<Approval(id={self.id}, expense_id={self.expense_id}, action={self.action})>"
