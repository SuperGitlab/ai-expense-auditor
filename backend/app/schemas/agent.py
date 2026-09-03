"""
AI Agent审核模式
定义AI审核工作流的请求/响应结构
"""
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class AIReviewRequest(BaseModel):
    """AI审核请求模式"""
    expense_id: int = Field(..., description="报销单ID")


class AIReviewResponse(BaseModel):
    """AI审核响应模式"""
    expense_id: int
    risk_level: str = Field(..., description="风险等级: low/medium/high")
    risk_score: Decimal = Field(..., description="风险分数 0-100")
    decision: str = Field(..., description="最终裁决: auto_approve/manual_review/auto_reject")
    review_result: str = Field(..., description="审核结果说明")
    suggestions: List[str] = Field(default_factory=list, description="改进建议")
    relevant_rules: List[str] = Field(default_factory=list, description="相关制度")
    similar_cases: List[dict] = Field(default_factory=list, description="相似案例")
    rule_violations: List[dict] = Field(default_factory=list, description="命中的规则明细")
    workflow_errors: List[str] = Field(default_factory=list, description="工作流节点错误记录")
    elapsed_seconds: Optional[float] = Field(None, description="审核耗时（秒）")
