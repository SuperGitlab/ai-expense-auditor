"""
规则导入数据模式
JSON直导与制度文档导入两通道共用的请求/响应结构
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.rule import RuleOperator, RuleSeverity, RuleType
from app.schemas.rule import RuleResponse

# 单次导入行数上限（防误传超大payload）
MAX_IMPORT_ROWS = 500


class RuleImportItem(BaseModel):
    """单条导入行（字段约束同 RuleBase；category_code 优先于 category_id 解析）"""
    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    code: str = Field(..., min_length=1, max_length=50, description="规则代码")
    rule_type: RuleType = RuleType.CUSTOM
    category_code: Optional[str] = Field(None, max_length=50, description="费用类别代码（优先于category_id）")
    category_id: Optional[int] = Field(None, description="限定费用类别ID（空=全类别）")
    field_name: str = Field(..., max_length=50, description="作用字段")
    operator: RuleOperator
    threshold: Optional[str] = Field(None, max_length=200, description="阈值")
    severity: RuleSeverity = RuleSeverity.WARN
    risk_points: int = Field(10, ge=0, le=100, description="命中计入风险分")
    description: Optional[str] = Field(None, max_length=500, description="规则说明")
    is_active: bool = Field(True, description="是否启用")

    @field_validator("category_code", "threshold", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        """空串/纯空白归一为None（前端下拉清空与空输入框会产生''）"""
        if isinstance(v, str):
            v = v.strip()
        return v or None


class RuleImportJsonRequest(BaseModel):
    """JSON直导请求体

    rules收原始dict而非RuleImportItem：坏行要在service里逐行校验成中文行错误
    （400逐行明细），而不是被FastAPI整体422（错误定位不友好）
    """
    rules: list[dict] = Field(..., min_length=1, max_length=MAX_IMPORT_ROWS)


class RuleImportRowError(BaseModel):
    """单行校验错误（400响应里与detail平级的errors明细）"""
    index: int = Field(..., description="0-based行号")
    code: Optional[str] = Field(None, description="该行的code（可能缺失）")
    errors: list[str] = Field(default_factory=list, description="该行全部错误")


class SectionOut(BaseModel):
    """制度原文章节（原文保真切块，不经LLM转述）"""
    title: str = ""
    content: str


class DraftRuleOut(RuleImportItem):
    """LLM抽取的规则草稿行（附原文依据与轻校验标注，供预览核对）"""
    quote: str = Field("", description="支撑该规则的原文片段（逐字复制）")
    issues: list[str] = Field(default_factory=list, description="轻校验问题（不阻断，人工预览时核对）")


class ExtractionDraftResponse(BaseModel):
    """文档抽取响应：草稿+章节由前端暂存，确认时原样回传"""
    filename: str
    source: str = Field(..., description="向量库 metadata.source（默认=文件名）")
    sections: list[SectionOut]
    rules: list[DraftRuleOut]
    stats: dict = Field(default_factory=dict, description="{text_chars, sections, rules, method}")


class ExtractionSubmitResponse(BaseModel):
    """抽取任务提交回执（解析在Celery后台跑，轮询status端点取结果）"""
    task_id: str = Field(..., description="Celery任务ID")
    filename: str = Field(..., description="上传文件名（完成通知里引用）")


class ExtractionStatusResponse(BaseModel):
    """抽取任务状态轮询响应"""
    state: str = Field(..., description="PENDING排队/STARTED执行中/SUCCESS完成/FAILURE失败")
    draft: Optional[ExtractionDraftResponse] = None
    error: Optional[str] = None


class DocumentImportConfirmRequest(BaseModel):
    """文档导入确认请求（sections必填：rules可为空=仅导入原文入知识库）"""
    source: str = Field(..., min_length=1, max_length=200)
    mode: Literal["append", "replace"] = "append"
    rules: list[dict] = Field(default_factory=list, max_length=MAX_IMPORT_ROWS)
    sections: list[SectionOut] = Field(..., min_length=1)


class ImportResultResponse(BaseModel):
    """导入结果（vector_* 仅文档通道有意义；JSON通道恒0/False）"""
    imported: int = Field(..., description="写入Rule表行数")
    rules: list[RuleResponse] = Field(default_factory=list)
    vector_written: int = Field(0, description="知识库(Milvus)入库块数")
    vector_available: bool = Field(False, description="Milvus是否可用")
    cleared_policies: bool = Field(False, description="replace模式是否执行了清空")
