"""
决策Agent
LLM给出决策建议与理由；最终裁决由确定性代码执行
（auto_approve/manual_review/auto_reject不交给LLM定夺）。
"""
import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentResult, BaseAgent


class ReviewDecision(BaseModel):
    """LLM结构化输出：决策建议"""
    suggestion: str = Field(..., description="建议动作: auto_approve/manual_review/auto_reject")
    reason: str = Field(..., description="决策理由（给申请人和审批人看）")
    suggestions: List[str] = Field(default_factory=list, description="给申请人的改进建议")


class DecisionAgent(BaseAgent):
    """决策Agent：综合全部审核结果给出终审建议"""

    def __init__(self):
        super().__init__(name="决策Agent")
        # GLM兼容接口不支持OpenAI的response_format，必须显式走tool-call模式
        self.structured_llm = self.llm.with_structured_output(
            ReviewDecision, method="function_calling"
        )

    def get_system_prompt(self) -> str:
        return (
            "你是财务审核终审专家。基于前序审核结果（单据检查/规则引擎/风险评估/知识检索）"
            "给出报销处理建议：\n"
            "- auto_approve：低风险且无违规，建议自动通过\n"
            "- manual_review：存在需要人工判断的事项，建议转人工审批\n"
            "- auto_reject：存在硬性违规（无发票/发票重复/单据造假迹象），建议自动驳回\n"
            "reason用对申请人友善但专业的中文说明。suggestions给出可操作的改进建议（可空）。"
        )

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        input_data: {"expense": snapshot, "document": ..., "rules": ..., "rag": ..., "risk": ...}
        """
        snapshot = input_data["expense"]
        document = input_data.get("document", {})
        rules_result = input_data.get("rules", {})
        rag_result = input_data.get("rag", {})
        risk_result = input_data.get("risk", {})
        errors = input_data.get("errors", [])

        llm_decision: ReviewDecision | None = None
        try:
            prompt = (
                f"报销单：{json.dumps(snapshot['expense'], ensure_ascii=False)}\n"
                f"明细：{json.dumps(snapshot['items'], ensure_ascii=False)}\n\n"
                f"[单据检查] {json.dumps({'anomalies': document.get('anomalies', []), 'verified': document.get('invoice_verified')}, ensure_ascii=False)}\n"
                f"[规则引擎] {json.dumps({'violations': rules_result.get('violations', []), 'hard_blocked': rules_result.get('hard_blocked')}, ensure_ascii=False)}\n"
                f"[风险评估] {json.dumps({'score': risk_result.get('risk_score'), 'level': risk_result.get('risk_level'), 'factors': risk_result.get('factors', [])}, ensure_ascii=False)}\n"
                f"[知识检索] 制度: {json.dumps(rag_result.get('relevant_rules', [])[:2], ensure_ascii=False)}\n"
                f"[工作流异常] {json.dumps(errors, ensure_ascii=False)}\n"
                "请给出终审建议。注意：工作流有异常时倾向 manual_review（保守策略）。"
            )
            llm_decision = await self.structured_chat(prompt)
        except Exception as e:
            errors = list(errors) + [f"LLM决策失败: {e}"]

        # ===== 确定性最终裁决（不采信LLM的动作建议）=====
        hard_blocked = bool(rules_result.get("hard_blocked"))
        forced_review = bool(rules_result.get("forced_review"))
        level = risk_result.get("risk_level", "medium")
        has_errors = bool(errors)

        if hard_blocked:
            action = "auto_reject"
        elif (level == "low" and not forced_review and not has_errors
              and document.get("invoice_verified", False)):
            action = "auto_approve"
        else:
            # medium/high、REVIEW规则命中、工作流异常、单据未验证 → 全部转人工（保守）
            action = "manual_review"

        # 理由与建议：优先用LLM生成的，失败时用机械模板
        if llm_decision:
            reason = llm_decision.reason
            suggestions = llm_decision.suggestions
        else:
            reason = self._fallback_reason(action, rules_result, risk_result)
            suggestions = [v["detail"] for v in rules_result.get("violations", [])][:3]

        data = {
            "action": action,
            "llm_suggestion": llm_decision.suggestion if llm_decision else None,
            "reason": reason,
            "suggestions": suggestions,
        }
        return AgentResult(success=True, data=data, message=f"裁决: {action}")

    @staticmethod
    def _fallback_reason(action: str, rules_result: dict, risk_result: dict) -> str:
        """LLM不可用时的机械理由模板"""
        if action == "auto_reject":
            details = "；".join(v["detail"] for v in rules_result.get("violations", []) if v["severity"] == "block")
            return f"命中硬性违规规则，自动驳回：{details}"
        if action == "auto_approve":
            return f"风险分 {risk_result.get('risk_score')}（低），无违规记录，自动通过。"
        return f"风险分 {risk_result.get('risk_score')}（{risk_result.get('risk_level')}），需人工复核。"
