"""
风险评估Agent
综合单据异常、规则命中、相似案例，用LLM评估风险分；
最终分=max(LLM分, 确定性规则分)——LLM只能加分不能漏报，
风险等级由代码阈值判定（不让LLM定级）。
"""
import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentResult, BaseAgent
from app.config import settings


class RiskAssessment(BaseModel):
    """LLM结构化输出：风险评估"""
    risk_score: float = Field(..., ge=0, le=100, description="风险分数0-100")
    factors: List[str] = Field(default_factory=list, description="风险因素")
    reasoning: str = Field("", description="评估理由")


class RiskAgent(BaseAgent):
    """风险评估Agent"""

    def __init__(self):
        super().__init__(name="风险评估Agent")
        # GLM兼容接口不支持response_format，走tool-call模式（基类helper同时记录schema供日志打印）
        self.structured_llm = self._make_structured_llm(RiskAssessment)

    def get_system_prompt(self) -> str:
        return (
            "你是财务风险控制专家，评估报销单的财务合规风险（0-100分，分数越高风险越大）。\n"
            "评分参考：\n"
            "- 0-40（低）：信息完整、金额合理、无违规迹象，可自动通过\n"
            "- 41-69（中）：存在轻度异常（超限额、说明简略、高频报销），建议人工复核\n"
            "- 70-100（高）：明显违规迹象（无发票、发票重复、金额拆分、单据矛盾），须严审\n"
            "factors列出每个扣分点及分值。不确定的信息按中性处理，不要凭空臆测风险。"
        )

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        input_data: {"expense": snapshot, "document": ..., "rules": ..., "rag": ...}
        """
        snapshot = input_data["expense"]
        document = input_data.get("document", {})
        rules_result = input_data.get("rules", {})
        rag_result = input_data.get("rag", {})

        llm_score = 0.0
        factors: List[str] = []
        reasoning = ""
        degraded = False

        try:
            prompt = (
                f"报销单：{json.dumps(snapshot['expense'], ensure_ascii=False)}\n"
                f"明细：{json.dumps(snapshot['items'], ensure_ascii=False)}\n"
                f"申请人：{json.dumps(snapshot['applicant'], ensure_ascii=False)}\n\n"
                f"[单据检查] 异常: {json.dumps(document.get('anomalies', []), ensure_ascii=False)}\n"
                f"[规则引擎] 确定性得分 {rules_result.get('points', 0)}，"
                f"命中: {json.dumps(rules_result.get('violations', []), ensure_ascii=False)}\n"
                f"[知识检索] 相关制度: {json.dumps(rag_result.get('relevant_rules', [])[:3], ensure_ascii=False)}\n"
                f"相似案例: {json.dumps(rag_result.get('similar_cases', [])[:3], ensure_ascii=False)}\n"
                "请综合评估风险分。"
            )
            result: RiskAssessment = await self.structured_chat(prompt)
            llm_score = float(result.risk_score)
            factors = result.factors
            reasoning = result.reasoning
        except Exception as e:
            degraded = True
            reasoning = f"LLM评估不可用，按确定性规则分评估（{e}）"

        # 最终分 = max(LLM分, 规则确定性分)：LLM只能加分不能漏报
        rule_points = float(rules_result.get("points", 0))
        final_score = round(max(llm_score, rule_points), 2)

        # 等级由代码阈值判定（确定性）
        if final_score < settings.RISK_LOW_MAX:
            level = "low"
        elif final_score >= settings.RISK_HIGH_MIN:
            level = "high"
        else:
            level = "medium"

        if rule_points > 0 and (not factors or degraded):
            factors = [v["detail"] for v in rules_result.get("violations", [])] or factors

        data = {
            "risk_score": final_score,
            "risk_level": level,
            "llm_score": llm_score,
            "rule_points": rule_points,
            "factors": factors,
            "reasoning": reasoning,
            "degraded": degraded,
        }
        return AgentResult(success=True, data=data, message=f"风险分 {final_score}（{level}）")
