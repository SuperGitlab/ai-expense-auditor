"""
站内通知数据模型
审核结果通知（AI审核/人工审批/打款登记）
"""
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, ForeignKey,
                        Integer, String, Text)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base


class Notification(Base):
    """
    站内通知表模型
    每条通知一行，按 user_id 隔离
    """

    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="收件人ID")
    title = Column(String(200), nullable=False, comment="通知标题")
    content = Column(Text, comment="通知内容")
    type = Column(String(20), default="system", nullable=False, comment="通知类型: ai_review/approval/payment")
    is_read = Column(Boolean, default=False, nullable=False, index=True, comment="是否已读")

    # server_default：与Expense.created_at同理，以数据库时钟为准
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")

    user = relationship("User", backref="notifications")

    def __repr__(self):
        return f"<Notification(id={self.id}, user_id={self.user_id}, title={self.title})>"
