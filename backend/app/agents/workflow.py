"""
LangGraph审核工作流
多Agent协作编排：单据解析 → [规则校验 ∥ RAG检索] → 风险评估 → 决策

设计要点：
- errors字段配operator.add reducer（rule/rag并行节点都写它，必须声明合并策略）
- 每个节点try/except：单个Agent失败写入errors给中性默认值，不让整图崩溃
- 关键裁决（auto_approve/auto_reject）由确定性代码执行，LLM仅提供建议
- _traced埋点：每节点running/succeeded/failed轨迹落agent_node_runs（画布可视化）
- 人审优先守卫：落库前行锁读单据，人工已接管（状态离开SUBMITTED/PENDING）则AI结论只留档不生效
  （PENDING=Celery失败兜底态尚无人工决定，重跑/断点恢复的结果允许落库）
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
from app.database import SessionLocal
from app.models import (AgentNodeRun, Approval, ApprovalAction, Expense,
                        ExpenseStatus, Rule, UserRole)
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
    """执行Agent并打印请求参数与返回结果（工作流观测）；星号线分隔每个Agent的日志块"""
    logger.info("*" * 60)
    logger.info(f"Agent[{agent.name}] ▶ 请求参数:\n{_dump(input_data)}")
    result = await agent.run(input_data)
    logger.info(
        f"Agent[{agent.name}] ◀ 返回结果:\n"
        f"{_dump({'success': result.success, 'message': result.message, 'data': result.data})}"
    )
    return result


# ===== 节点轨迹埋点（画布可视化 + 人工接管观测） =====
def _summarize_document(r: dict) -> str:
    doc = r.get("document", {})
    anomalies = doc.get("anomalies") or []
    summary = (doc.get("summary") or "").strip()
    text = f"解析完成，异常{len(anomalies)}项"
    return f"{text}：{summary[:60]}" if summary else text


def _summarize_rule(r: dict) -> str:
    v = r.get("rules", {})
    blocked = "是" if v.get("hard_blocked") else "否"
    return f"命中违规{len(v.get('violations') or [])}项，硬阻断={blocked}"


def _summarize_rag(r: dict) -> str:
    g = r.get("rag", {})
    return f"检索制度{len(g.get('relevant_rules') or [])}条、相似案例{len(g.get('similar_cases') or [])}条"


def _summarize_risk(r: dict) -> str:
    k = r.get("risk", {})
    return f"风险分{k.get('risk_score', '-')}（{k.get('risk_level', '-')}）"


def _summarize_decision(r: dict) -> str:
    d = r.get("decision", {})
    reason = (d.get("reason") or "").strip()
    text = f"裁决：{d.get('action', '-')}"
    return f"{text}——{reason[:60]}" if reason else text


_NODE_SUMMARIES = {
    "document": _summarize_document,
    "rule": _summarize_rule,
    "rag": _summarize_rag,
    "risk": _summarize_risk,
    "decision": _summarize_decision,
}

# 节点名 → 其写入state的key（注意rule节点写的是rules复数键）
# 断点恢复按此映射判断"本节点输出已在state里"→ 跳过重跑
_NODE_STATE_KEYS = {
    "document": "document",
    "rule": "rules",
    "rag": "rag",
    "risk": "risk",
    "decision": "decision",
}

_OUTPUT_JSON_LIMIT = 60_000  # TEXT 64KB守卫：超长放弃断点（该节点下次整跑）


def _dump_output(value) -> str | None:
    """节点输出序列化为checkpoint JSON；超长或不可序列化返回None（不存截断的坏JSON）"""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"节点输出不可序列化，放弃断点checkpoint: {e}")
        return None
    if len(text) > _OUTPUT_JSON_LIMIT:
        logger.warning(f"节点输出超{_OUTPUT_JSON_LIMIT}字符，放弃断点checkpoint")
        return None
    return text


def _record_node(
    db: Session, expense_id: int, node: str, status: str,
    detail: str | None = None, error: str | None = None,
    output_json: str | None = None,
) -> AgentNodeRun:
    """按(expense_id,node) upsert节点轨迹并立即提交（画布3s轮询实时可见）"""
    run = db.query(AgentNodeRun).filter(
        AgentNodeRun.expense_id == expense_id, AgentNodeRun.node == node
    ).first()
    if run is None:
        run = AgentNodeRun(expense_id=expense_id, node=node, started_at=utc_now())
        db.add(run)
    run.status = status
    if status == "running":
        # 重跑同一节点：刷新开始时间（续跑时长不失真、sweep判活准确），旧checkpoint作废
        run.started_at = utc_now()
    run.finished_at = utc_now() if status != "running" else None
    run.detail = (detail or "")[:500] or None
    run.error = (error or "")[:500] or None
    run.output_json = output_json
    db.commit()
    return run


def _node_session() -> Session:
    """节点轨迹专用短会话：节点本体保持纯函数不持有Session，
    埋点独立开session即时提交，画布轮询才能看到执行中状态"""
    return SessionLocal()


def _record_node_quiet(expense_id: int, node: str, status: str,
                       detail: str | None = None, error: str | None = None,
                       output_json: str | None = None) -> None:
    """埋点写入失败不影响审核主流程（只log）"""
    try:
        with _node_session() as db:
            _record_node(db, expense_id, node, status, detail, error, output_json)
    except Exception as e:
        logger.warning(f"节点轨迹写入失败（不影响审核）: {node}/{status}: {e}")


def _traced(name: str, fn):
    """节点埋点包装：进入记running；正常完成记succeeded+摘要并持久化输出（断点checkpoint）；
    节点降级（自身捕获异常返回errors）或抛异常记failed；异常继续上抛由外层兜底；
    断点续跑：state里已有本节点输出（run(resume=True)注入）→ 跳过不重调、不重记埋点"""
    async def wrapped(state: ExpenseReviewState) -> dict:
        key = _NODE_STATE_KEYS[name]
        if state.get(key) is not None:
            return {}  # 已有成功输出，画布保留原时间戳
        expense_id = state["expense_id"]
        _record_node_quiet(expense_id, name, "running")
        try:
            result = await fn(state)
        except Exception as e:
            _record_node_quiet(expense_id, name, "failed", error=str(e))
            raise
        node_errors = result.get("errors") or []
        if node_errors:
            _record_node_quiet(expense_id, name, "failed", error=str(node_errors[0]))
        else:
            _record_node_quiet(expense_id, name, "succeeded",
                               detail=_NODE_SUMMARIES[name](result),
                               output_json=_dump_output(result.get(key)))
        return result
    return wrapped


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
    graph.add_node("document", _traced("document", document_node))
    graph.add_node("rule", _traced("rule", rule_node))
    graph.add_node("rag", _traced("rag", rag_node))
    graph.add_node("risk", _traced("risk", risk_node))
    graph.add_node("decision", _traced("decision", decision_node))

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

    async def run(self, db: Session, expense_id: int, *, resume: bool = False) -> dict:
        """
        执行完整AI审核

        Args:
            resume: 断点续跑——保留已成功节点轨迹，其输出JSON注入state由_traced跳过，
                    仅重跑failed/未执行节点（不重复调用LLM）

        Returns:
            dict: AIReviewResponse结构的审核结果
        """
        started = time.time()

        if resume:
            # 0a. 断点续跑：遗留running行（worker中断）标failed，画布不留假执行中
            db.query(AgentNodeRun).filter(
                AgentNodeRun.expense_id == expense_id,
                AgentNodeRun.status == "running",
            ).update(
                {
                    "status": "failed",
                    "error": "执行中断（worker停止），已断点续跑",
                    "finished_at": utc_now(),
                    "output_json": None,
                },
                synchronize_session=False,
            )
            db.commit()
            checkpoints = db.query(AgentNodeRun).filter(
                AgentNodeRun.expense_id == expense_id,
                AgentNodeRun.status == "succeeded",
                AgentNodeRun.output_json.isnot(None),
            ).all()
        else:
            # 0b. 整轮重跑：清空上一轮节点轨迹（画布只显示最新一轮）
            db.query(AgentNodeRun).filter(AgentNodeRun.expense_id == expense_id).delete(
                synchronize_session=False
            )
            db.commit()
            checkpoints = []

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
        # 断点注入：成功节点输出直接进state，_traced见自身key已存在即跳过（不重调LLM）
        for row in checkpoints:
            key = _NODE_STATE_KEYS.get(row.node)
            if not key:
                continue
            try:
                value = json.loads(row.output_json)
            except (TypeError, ValueError):
                logger.warning(f"节点{row.node}的checkpoint JSON损坏，忽略")
                continue
            if isinstance(value, dict):
                init_state[key] = value
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

        result = {
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

        # 4. 落库：报销单AI字段 + 审批记录 + 状态流转
        # 行锁读当前状态：人工接管与AI落库并发时，以先提交的事务为准
        # （populate_existing强制按最新行刷新——会话identity map里可能还是快照时的旧状态）
        expense = (
            db.query(Expense)
            .with_for_update()
            .populate_existing()
            .filter(Expense.id == expense_id)
            .first()
        )
        if expense is None:
            raise ValueError(f"报销单#{expense_id}不存在，AI审核结果无处落库")

        def _ai_review_record() -> Approval:
            """AI审核流水（无论是否被人审接管都留档，供时间线回看）"""
            return Approval(
                expense_id=expense_id,
                approver_id=None,
                approver_name="AI审核系统",
                action=ApprovalAction.AI_REVIEW,
                comment=decision.get("reason", ""),
                risk_level=risk_level,
                risk_score=risk_score,
                ai_decision=action,
            )

        if expense.status not in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
            # 人审优先守卫：AI执行期间人工已接管（状态离开SUBMITTED/PENDING）
            # → 单据任何字段都不写（人审结果为准），AI结论仅留档：
            #   AI_REVIEW流水 + 决策节点标overridden
            # （PENDING=Celery失败兜底态，尚无人工决定，重跑/断点恢复的结果允许落库）
            _record_node(db, expense_id, "decision", "overridden",
                         detail=(f"人审结果优先：人工已将单据流转为 {expense.status.value}，"
                                 f"AI裁决（{action}）仅留档"))
            db.add(_ai_review_record())
            db.commit()
            logger.info(
                f"AI审核被人审接管 报销单#{expense_id}: 人工终态={expense.status.value} "
                f"AI裁决={action}（仅留档不生效）"
            )
            return result

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

        db.add(_ai_review_record())
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

        return result


# 工作流单例
workflow = ExpenseReviewWorkflow()
