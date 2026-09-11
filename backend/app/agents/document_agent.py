"""
文档解析Agent
单据一致性检查：发票文本提取、金额合计核对、发票完整性、品类语义匹配
"""
import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentResult, BaseAgent
from app.tools import ocr_tool


class DocumentCheck(BaseModel):
    """LLM结构化输出：单据一致性检查结果"""
    invoice_verified: bool = Field(..., description="发票信息是否完整可信")
    anomalies: List[str] = Field(default_factory=list, description="发现的异常列表")
    summary: str = Field(..., description="单据检查结论（一句话）")


class DocumentAgent(BaseAgent):
    """文档解析Agent：提取发票文本 + LLM一致性检查"""

    def __init__(self):
        super().__init__(name="文档解析Agent")
        # 结构化输出模型（GLM兼容接口不支持OpenAI的response_format，必须显式走tool-call模式）
        self.structured_llm = self.llm.with_structured_output(
            DocumentCheck, method="function_calling"
        )

    def get_system_prompt(self) -> str:
        return (
            "你是财务单据审核专家，负责对报销单做单据层面的完整性一致性检查。\n"
            "检查要点：\n"
            "1. 明细金额合计是否等于报销总额\n"
            "2. 发票号是否缺失或格式异常（正常为8-20位数字/大写字母）\n"
            "3. 费用类别与费用说明是否语义匹配（如'餐饮费'报销的是机票）\n"
            "4. 费用日期是否明显不合理\n"
            "5. 单据提取文本与报销说明是否矛盾\n"
            "只报告确实存在的问题，不要臆测。anomalies中每条为简短中文描述。"
        )

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        input_data: {"expense": snapshot}
        """
        snapshot = input_data["expense"]
        expense = snapshot["expense"]
        items = snapshot["items"]

        # 1. 发票结构化提取（txt/docx直读+校验；图片/PDF走OCR流水线）
        #    经 ocr_tool 模块属性调用：测试通过 monkeypatch 注入假实现
        invoice_texts = {}
        ocr_items = {}
        for it in items:
            if it.get("invoice_url"):
                r = ocr_tool.read_invoice_ocr(
                    it["invoice_url"], declared_no=it.get("invoice_no")
                )
                if r is not None:
                    invoice_texts[f"明细#{it['id']}"] = ocr_tool.format_ocr_result(r)
                    ocr_items[it["id"]] = {"verified": r.ok, "anomalies": r.anomalies}

        # 2. 交给LLM做一致性判断
        prompt = (
            f"报销单信息：\n{json.dumps(expense, ensure_ascii=False)}\n\n"
            f"报销明细：\n{json.dumps(items, ensure_ascii=False)}\n\n"
            f"单据提取文本（可能为空）：\n{json.dumps(invoice_texts, ensure_ascii=False)}\n\n"
            f"申请人近90天已提交 {snapshot['applicant']['recent_90d_count']} 张报销单，"
            f"合计 {snapshot['applicant']['recent_90d_total']} 元。\n"
            "请完成单据一致性检查。"
        )

        result: Optional[DocumentCheck] = None
        error = None
        try:
            result = await self.structured_chat(prompt)
        except Exception as e:
            error = f"LLM单据检查失败: {e}"

        # LLM失败时的确定性兜底：至少做金额合计核对
        if result is None:
            anomalies = []
            item_sum = round(sum(it["amount"] for it in items), 2)
            if abs(item_sum - float(expense["total_amount"])) > 0.01:
                anomalies.append(f"明细合计{item_sum}元与总额{expense['total_amount']}元不符")
            for it in items:
                if not it.get("invoice_no"):
                    anomalies.append(f"明细#{it['id']}缺少发票号")
            result = DocumentCheck(
                invoice_verified=not anomalies,
                anomalies=anomalies,
                summary="LLM不可用，已按确定性规则完成基础核对",
            )

        data = {
            "invoice_verified": result.invoice_verified,
            "anomalies": result.anomalies,
            "summary": result.summary,
            "invoice_texts": invoice_texts,
            "ocr_items": ocr_items,
        }
        if error:
            data["degraded"] = True
            data["degraded_reason"] = error

        return AgentResult(success=True, data=data, message=result.summary)
