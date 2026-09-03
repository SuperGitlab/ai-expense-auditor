"""
审批数据模式
定义审批记录、审批操作的 Pydantic 模式
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.approval import ApprovalAction


class ApprovalResponse(BaseModel):
    """审批记录响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    expense_id: int
    approver_id: Optional[int] = None
    approver_name: str
    action: ApprovalAction
    comment: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[Decimal] = None
    ai_decision: Optional[str] = None
    created_at: datetime


class ApprovalListResponse(BaseModel):
    """审批记录列表响应模式"""
    items: List[ApprovalResponse]
    total: int


class ApprovalDecisionRequest(BaseModel):
    """人工审批决策请求模式"""
    expense_id: int = Field(..., description="报销单ID")
    action: Literal["approve", "reject"] = Field(..., description="审批动作")
    comment: Optional[str] = Field(None, max_length=500, description="审批意见")


class PendingExpenseItem(BaseModel):
    """待审批报销单摘要（审批中心列表用）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    expense_no: str
    title: str
    user_id: int
    applicant_name: Optional[str] = None  # 冗余申请人姓名（Expense.applicant_name属性）
    total_amount: Decimal
    risk_level: Optional[str] = None
    risk_score: Optional[Decimal] = None
    submitted_at: Optional[datetime] = None
