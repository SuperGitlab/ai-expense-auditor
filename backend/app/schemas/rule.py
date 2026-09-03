"""
规则数据模式
定义审核规则的 Pydantic 模式
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.rule import RuleOperator, RuleSeverity, RuleType


class RuleBase(BaseModel):
    """规则基础模式"""
    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    code: str = Field(..., min_length=1, max_length=50, description="规则代码")
    rule_type: RuleType = Field(RuleType.CUSTOM, description="规则类型")
    category_id: Optional[int] = Field(None, description="限定费用类别ID（空=全类别）")
    field_name: str = Field(..., max_length=50, description="作用字段")
    operator: RuleOperator = Field(..., description="比较操作符")
    threshold: Optional[str] = Field(None, max_length=200, description="阈值")
    severity: RuleSeverity = Field(RuleSeverity.WARN, description="严重级别")
    risk_points: int = Field(10, ge=0, le=100, description="命中计入风险分")
    description: Optional[str] = Field(None, max_length=500, description="规则说明")
    is_active: bool = Field(True, description="是否启用")


class RuleCreate(RuleBase):
    """创建规则模式"""
    pass


class RuleUpdate(BaseModel):
    """更新规则模式"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    category_id: Optional[int] = None
    field_name: Optional[str] = Field(None, max_length=50)
    operator: Optional[RuleOperator] = None
    threshold: Optional[str] = Field(None, max_length=200)
    severity: Optional[RuleSeverity] = None
    risk_points: Optional[int] = Field(None, ge=0, le=100)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class RuleResponse(RuleBase):
    """规则响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
