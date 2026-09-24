"""
报销数据模式
定义报销单、报销项目相关的 Pydantic 模式
枚举统一从 models 导入（models为唯一真源，避免重复定义导致两边不一致）
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.expense import ExpenseStatus, ExpenseType


# ========== 报销项目模式 ==========


class ExpenseItemBase(BaseModel):
    """报销项目基础模式"""
    category_id: int = Field(..., description="费用类别ID")
    description: str = Field(..., min_length=1, max_length=500, description="费用说明")
    amount: Decimal = Field(..., gt=0, description="金额")
    expense_date: date = Field(..., description="费用发生日期")
    invoice_no: Optional[str] = Field(None, max_length=100, description="发票号码")
    invoice_url: Optional[str] = Field(None, max_length=500, description="发票文件URL")

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, v: date) -> date:
        """验证费用日期不能晚于今天"""
        if v > date.today():
            raise ValueError("费用发生日期不能晚于今天")
        return v


class ExpenseItemCreate(ExpenseItemBase):
    """创建报销项目模式"""
    pass


class ExpenseItemResponse(ExpenseItemBase):
    """报销项目响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    expense_id: int
    invoice_verified: bool
    created_at: datetime


# ========== 报销单模式 ==========


class ExpenseBase(BaseModel):
    """报销单基础模式"""
    title: str = Field(..., min_length=1, max_length=200, description="报销标题")
    expense_type: ExpenseType = Field(..., description="报销类型")
    description: Optional[str] = Field(None, description="报销说明")
    remark: Optional[str] = Field(None, description="备注")


class ExpenseCreate(ExpenseBase):
    """创建报销单模式（items 至少一条，由 min_length=1 保证）"""
    items: List[ExpenseItemCreate] = Field(..., min_length=1, description="报销项目列表")


class ExpenseUpdate(BaseModel):
    """更新报销单模式"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    expense_type: Optional[ExpenseType] = None
    description: Optional[str] = None
    remark: Optional[str] = None
    items: Optional[List[ExpenseItemCreate]] = None


class ExpenseResponse(ExpenseBase):
    """报销单响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    # 申请人信息（监管视角的"全部报销"列表返回；"我的报销"接口不填，为None）
    applicant_name: Optional[str] = None
    applicant_department: Optional[str] = None
    expense_no: str
    total_amount: Decimal
    currency: str
    status: ExpenseStatus
    risk_level: Optional[str] = None
    risk_score: Optional[Decimal] = None
    ai_review_result: Optional[str] = None
    rejection_reason: Optional[str] = None
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: List[ExpenseItemResponse] = []


class ExpenseListResponse(BaseModel):
    """报销单列表响应模式"""
    items: List[ExpenseResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
