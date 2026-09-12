"""
LangGraph审核工作流
多Agent协作编排：单据解析 → [规则校验 ∥ RAG检索] → 风险评估 → 决策

设计要点：
- errors字段配operator.add reducer（rule/rag并行节点都写它，必须声明合并策略）
- 每个节点try/except：单个Agent失败写入errors给中性默认值，不让整图崩溃
- 关键裁决（auto_approve/auto_reject）由确定性代码执行，LLM仅提供建议
"""
import json
import logging
import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.base_agent import AgentResult
from app.agents.decision_agent import DecisionAgent
from app.agents.document_agent import DocumentAgent
from app.agents.rag_agent import RAGAgent
from app.agents.risk_agent import RiskAgent
from app.agents.rule_agent import RuleAgent
from app.config import settings
from app.models import (Approval, ApprovalAction, Expense, ExpenseStatus, Rule,
                        UserRole)
from app.rag.knowledge_base import KnowledgeBaseManager
from app.services.expense_service import build_snapshot
from app.services.notification_service import notify_ai_review
from app.tools.database_tool import find_duplicate_invoice
from app.utils.helpers import utc_now

logger = logging.getLogger(__name__)


def _dump(obj: Any) -> str:
    """Agent出入参统一序列化：中文原样、不可序列化对象转str"""
    return json.dumps(obj, ensure_ascii=False, default=str, indent=2)


async def _run_with_log(agent: Any, input_data: dict) -> AgentResult:
    """执行Agent并打印请求参数与返回结果（工作流观测）"""
    logger.info(f"Agent[{agent.name}] ▶ 请求参数:\n{_dump(input_data)}")
    result = await agent.run(input_data)
    logger.info(
        f"Agent[{agent.name}] ◀ 返回结果:\n"
        f"{_dump({'success': result.success, 'message': result.message, 'data': result.data})}"
    )
    return result


# ===== 共享状态定义 =====
class ExpenseReviewState(TypedDict, total=False):
    """审核工作流共享状态（节点返回局部更新）"""
    expense_id: int
    expense: dict          # build_snapshot快照
    rules_data: dict       # 预加载的规则与重复发票检查结果 {rules, duplicates}
    document: dict         # DocumentAgent结果
    rules: dict            # RuleAgent结果（确定性引擎输出）
    rag: dict              # RAGAgent结果
    risk: dict             # RiskAgent结果
    decision: dict         # DecisionAgent结果
    # 并行节点(rule/rag)都会追加错误，必须声明reducer合并策略
    errors: Annotated[list[str], operator.add]
    started_at: float
    finished_at: float


# ===== Agent单例（LLM客户端复用，节点为纯函数不持有会话状态） =====
document_agent = DocumentAgent()
rule_agent = RuleAgent()
rag_agent = RAGAgent()
risk_agent = RiskAgent()
decision_agent = DecisionAgent()
knowledge_base = KnowledgeBaseManager()


# ===== 节点函数 =====
async def document_node(state: ExpenseReviewState) -> dict:
    """单据解析节点"""
    try:
        result: AgentResult = await _run_with_log(document_agent, {"expense": state["expense"]})
        return {"document": result.data}
    except Exception as e:
        logger.exception("document节点失败")
        return {
            "document": {"invoice_verified": False, "anomalies": [], "summary": ""},
            "errors": [f"文档解析节点失败: {e}"],
        }


async def rule_node(state: ExpenseReviewState) -> dict:
    """规则校验节点（与rag并行）"""
    try:
        result = await _run_with_log(rule_agent, {
            "expense": state["expense"],
            "rules_data": state.get("rules_data", {}),
        })
        return {"rules": result.data}
    except Exception as e:
        logger.exception("rule节点失败")
        return {
            "rules": {"violations": [], "hard_blocked": False, "forced_review": False, "points": 0},
            "errors": [f"规则校验节点失败: {e}"],
        }


async def rag_node(state: ExpenseReviewState) -> dict:
    """RAG检索节点（与rule并行）"""
    try:
        result = await _run_with_log(rag_agent, {"expense": state["expense"]})
        return {"rag": result.data}
    except Exception as e:
        logger.exception("rag节点失败")
        return {
            "rag": {"relevant_rules": [], "similar_cases": [], "retrieval_note": ""},
            "errors": [f"RAG检索节点失败: {e}"],
        }


async def risk_node(state: ExpenseReviewState) -> dict:
    """风险评估节点（上游rule/rag全部完成后执行）"""
    try:
        result = await _run_with_log(risk_agent, {
            "expense": state["expense"],
            "document": state.get("document", {}),
            "rules": state.get("rules", {}),
            "rag": state.get("rag", {}),
        })
        return {"risk": result.data}
    except Exception as e:
        logger.exception("risk节点失败")
        # 风险评估失败按高风险处理（保守）
        return {
            "risk": {"risk_score": 100.0, "risk_level": "high", "factors": [], "reasoning": str(e)},
            "errors": [f"风险评估节点失败: {e}"],
        }


async def decision_node(state: ExpenseReviewState) -> dict:
    """决策节点（终审）"""
    try:
        result = await _run_with_log(decision_agent, {
            "expense": state["expense"],
            "document": state.get("document", {}),
            "rules": state.get("rules", {}),
            "rag": state.get("rag", {}),
            "risk": state.get("risk", {}),
            "errors": state.get("errors", []),
        })
        return {"decision": result.data}
    except Exception as e:
        logger.exception("decision节点失败")
        return {
            "decision": {
                "action": "manual_review",
                "reason": f"决策节点异常，保守转人工审批: {e}",
                "suggestions": [],
            },
            "errors": [f"决策节点失败: {e}"],
        }


def build_graph():
    """
    构建并编译审核图：

    START → document → ┬→ rule ┐
                       └→ rag  ┴→ risk → decision → END
    """
    graph = StateGraph(ExpenseReviewState)
    graph.add_node("document", document_node)
    graph.add_node("rule", rule_node)
    graph.add_node("rag", rag_node)
    graph.add_node("risk", risk_node)
    graph.add_node("decision", decision_node)

    graph.add_edge(START, "document")
    graph.add_edge("document", "rule")    # fan-out：rule与rag并行
    graph.add_edge("document", "rag")
    graph.add_edge("rule", "risk")        # fan-in：risk等两个上游都完成
    graph.add_edge("rag", "risk")
    graph.add_edge("risk", "decision")
    graph.add_edge("decision", END)
    return graph.compile()


def _should_skip_manager_review(db: Session, expense: Expense) -> tuple[bool, str]:
    """确定性跳过经理初审判定：申请人本人是经理（不能自审）/ 部门无在职经理"""
    owner = expense.user
    if owner is None:
        return False, ""
    if owner.role == UserRole.MANAGER:
        return True, "申请人本人为经理，不能自审"
    if owner.department:
        from app.models import User
        has_manager = (
            db.query(User)
            .filter(
                User.role == UserRole.MANAGER,
                User.is_active.is_(True),
                User.department == owner.department,
            )
            .first()
            is not None
        )
        if not has_manager:
            return True, f"部门「{owner.department}」无在职经理"
    return False, ""


class ExpenseReviewWorkflow:
    """
    报销审核工作流：DB预加载 → LangGraph执行 → 结果落库 → 知识库回填
    """

    def __init__(self):
        self.app = build_graph()

    async def run(self, db: Session, expense_id: int) -> dict:
        """
        执行完整AI审核

        Returns:
            dict: AIReviewResponse结构的审核结果
        """
        started = time.time()

        # 1. DB预加载（节点保持纯函数，不在图中持有Session）
        # 获取报销清单信息
        snapshot = build_snapshot(db, expense_id)
        # 获取规则信息
        rules = [
            {
                "code": r.code, "name": r.name, "rule_type": r.rule_type.value,
                "category_id": r.category_id, "field_name": r.field_name,
                "operator": r.operator.value, "threshold": r.threshold,
                "severity": r.severity.value, "risk_points": r.risk_points,
            }
            for r in db.query(Rule).filter(Rule.is_active == True).all()  # noqa: E712
        ]
        duplicates = []
        for item in snapshot["items"]:
            dup = find_duplicate_invoice(db, item.get("invoice_no"), exclude_expense_id=expense_id)
            if dup:
                duplicates.append(dup)

        # 2. 执行LangGraph图
        init_state: ExpenseReviewState = {
            "expense_id": expense_id,
            "expense": snapshot,
            "rules_data": {"rules": rules, "duplicates": duplicates},
            "errors": [],
            "started_at": started,
        }
        final_state = await self.app.ainvoke(
            init_state, config={"recursion_limit": 20}
        )
        finished = time.time()
        elapsed = round(finished - started, 2)

        # 3. 汇总结果
        risk = final_state.get("risk", {})
        decision = final_state.get("decision", {})
        rules_result = final_state.get("rules", {})
        rag_result = final_state.get("rag", {})
        errors = final_state.get("errors", [])
        action = decision.get("action", "manual_review")
        risk_score = risk.get("risk_score", 100.0)
        risk_level = risk.get("risk_level", "high")

        review_result = {
            "reason": decision.get("reason", ""),
            "suggestions": decision.get("suggestions", []),
            "rule_violations": rules_result.get("violations", []),
            "document_anomalies": final_state.get("document", {}).get("anomalies", []),
            "llm_suggestion": decision.get("llm_suggestion"),
            "risk_factors": risk.get("factors", []),
        }

        # 4. 落库：报销单AI字段 + 审批记录 + 状态流转
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        expense.risk_level = risk_level
        expense.risk_score = risk_score
        expense.ai_review_result = json.dumps(review_result, ensure_ascii=False)

        # 回写明细发票校验结果（OCR/直读校验全过=True；无发票文件的明细不动）
        ocr_items = final_state.get("document", {}).get("ocr_items") or {}
        for it in expense.items:
            ocr = ocr_items.get(it.id)
            if ocr is not None:
                it.invoice_verified = ocr["verified"]

        if action == "auto_approve":
            expense.status = ExpenseStatus.APPROVED
            expense.approved_at = utc_now()
        elif action == "auto_reject":
            expense.status = ExpenseStatus.REJECTED
            expense.rejection_reason = decision.get("reason", "AI审核驳回")
        else:
            # 转人工：按确定性规则决定是否跳过经理初审
            skip, skip_reason = _should_skip_manager_review(db, expense)
            if skip:
                expense.status = ExpenseStatus.MANAGER_APPROVED
                db.add(Approval(
                    expense_id=expense_id,
                    approver_id=None,
                    approver_name="系统（自动跳过初审）",
                    action=ApprovalAction.APPROVE,
                    comment=f"自动跳过经理初审：{skip_reason}",
                    step="manager",
                ))
            else:
                expense.status = ExpenseStatus.PENDING

        db.add(Approval(
            expense_id=expense_id,
            approver_id=None,
            approver_name="AI审核系统",
            action=ApprovalAction.AI_REVIEW,
            comment=decision.get("reason", ""),
            risk_level=risk_level,
            risk_score=risk_score,
            ai_decision=action,
        ))
        db.commit()

        # 4.5 通知申请人（站内信必有、邮件尽力而为；失败不影响审核结果）
        try:
            notify_ai_review(db, expense, action, decision.get("reason", ""))
        except Exception as e:
            logger.warning(f"AI审核通知失败（不影响主流程）: {e}")

        # 5. 知识库回填（失败不影响主流程）
        try:
            knowledge_base.add_case_from_expense(snapshot, {
                "action": action,
                "reason": decision.get("reason", ""),
                "risk_level": risk_level,
                "risk_score": risk_score,
                "final_status": expense.status.value,
            })
        except Exception as e:
            logger.warning(f"知识库回填失败: {e}")

        logger.info(
            f"AI审核完成 报销单#{expense_id}: {action} 风险{risk_score}({risk_level}) "
            f"耗时{elapsed}s 错误{len(errors)}个"
        )

        return {
            "expense_id": expense_id,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "decision": action,
            "review_result": json.dumps(review_result, ensure_ascii=False),
            "suggestions": decision.get("suggestions", []),
            "relevant_rules": rag_result.get("relevant_rules", []),
            "similar_cases": rag_result.get("similar_cases", []),
            "rule_violations": rules_result.get("violations", []),
            "workflow_errors": errors,
            "elapsed_seconds": elapsed,
        }


# 工作流单例
workflow = ExpenseReviewWorkflow()
