"""
Agent节点执行轨迹模型
每轮AI审核5个节点（document/rule/rag/risk/decision）各自的状态，
驱动前端画布实时可视化；成功节点的输出JSON持久化在output_json，
断点恢复时直接复用、不重调LLM
"""
from sqlalchemy import (BigInteger, Column, DateTime, ForeignKey, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base


class AgentNodeRun(Base):
    """
    节点轨迹表模型
    一轮审核内 (expense_id, node) 唯一；status:
    running=执行中 / succeeded=完成 / failed=失败 / overridden=被人审接管覆盖
    """

    __tablename__ = "agent_node_runs"
    __table_args__ = (
        UniqueConstraint("expense_id", "node", name="uq_agent_node_runs_expense_node"),
    )

    # 主键
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # 关联报销单
    expense_id = Column(BigInteger, ForeignKey("expenses.id"), nullable=False, comment="报销单ID")

    # 节点与状态
    node = Column(String(20), nullable=False, comment="节点名: document/rule/rag/risk/decision")
    status = Column(String(20), nullable=False, comment="状态: running/succeeded/failed/overridden")

    # 时间戳
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="开始时间")
    finished_at = Column(DateTime(timezone=True), comment="结束时间")

    # 结果
    detail = Column(String(500), comment="结果摘要")
    error = Column(String(500), comment="失败原因")
    output_json = Column(Text, comment="成功节点输出JSON（断点续跑checkpoint）")

    # 关联关系
    expense = relationship("Expense", back_populates="node_runs")

    def __repr__(self):
        return f"<AgentNodeRun(id={self.id}, expense_id={self.expense_id}, node={self.node}, status={self.status})>"
