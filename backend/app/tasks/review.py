"""
AI审核Celery任务 + worker启动自愈扫描（卡死单断点重派）
"""
import asyncio
import logging
from datetime import datetime, timedelta

from celery.signals import worker_ready

from app.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="review.run_ai_review")
def run_ai_review(expense_id: int, resume: bool = False) -> str:
    """
    执行AI审核工作流（提交链路唯一执行方，无进程内降级）：
    自开session（worker进程独立于请求生命周期）、失败保守转PENDING人工。
    resume=True断点续跑：复用已成功节点输出，仅重跑failed/未执行节点。
    workflow.run是async，worker里用asyncio.run驱动；返回字符串作为任务结果便于观测。
    """
    from app.agents.workflow import workflow as review_workflow
    from app.database import SessionLocal
    from app.models import Expense, ExpenseStatus

    db = SessionLocal()
    try:
        # 人审优先（任务起点守卫）：人工已裁决（状态离开SUBMITTED/PENDING）则直接跳过——
        # 不跑工作流、不烧LLM、不清节点轨迹。覆盖两类场景：排队中的任务等到了人审落定；
        # worker中途死掉的消息经visibility timeout重投时人早已审完（顺带补标记残留节点）
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if expense and expense.status not in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
            logger.info("跳过AI审核 报销单#%s: 人工已裁决（状态=%s）", expense_id, expense.status.value)
            try:
                from app.agents.workflow import mark_nodes_human_first
                mark_nodes_human_first(db, expense_id, expense.status.value)
            except Exception as e:
                logger.warning("跳过时节点补标记失败（不影响任务）: 报销单#%s, err=%s", expense_id, e)
            return f"expense#{expense_id} skipped: human decided"
        asyncio.run(review_workflow.run(db, expense_id, resume=resume))
        return f"expense#{expense_id} reviewed"
    except Exception as e:
        # AI审核失败：保守转人工，单据留在PENDING状态，不影响提交本身
        # 人审优先：人工已接管（状态离开SUBMITTED）则不再改状态
        logger.exception("后台AI审核失败（转人工）: 报销单#%s, err=%s", expense_id, e)
        db.rollback()
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if expense and expense.status == ExpenseStatus.SUBMITTED:
            expense.status = ExpenseStatus.PENDING
            db.commit()
        return f"expense#{expense_id} fallback_to_pending: {e}"
    finally:
        db.close()


def find_stuck_expense_ids(db, now: datetime, grace_minutes: int = 15) -> list[int]:
    """
    自愈扫描目标：SUBMITTED 且提交超过宽限期、且宽限期内无任何节点进展
    （无节点行=任务从未被worker执行；节点行全旧=worker中途死掉）。
    只扫SUBMITTED：PENDING是失败兜底态（已入人工队列），自动重试会造成LLM重试风暴。
    MySQL DATETIME无时区：now统一转naive再比较。
    """
    from app.models import AgentNodeRun, Expense, ExpenseStatus

    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    cutoff = now_naive - timedelta(minutes=grace_minutes)

    """
    SELECT expenses.id
    FROM expenses
    WHERE expenses.status = %(status_1)s
    AND expenses.submitted_at IS NOT NULL
    AND expenses.submitted_at < %(submitted_at_1)s
    AND NOT EXISTS (
        SELECT agent_node_runs.id
        FROM agent_node_runs
        WHERE agent_node_runs.expense_id = expenses.id
            AND agent_node_runs.started_at >= %(started_at_1)s
    )
    -- 参数: {'status_1': 'submitted',
    --        'submitted_at_1': datetime(2026, 9, 21, 14, 55),
    --        'started_at_1':   datetime(2026, 9, 21, 14, 55)}

    """

    rows = (
        db.query(Expense.id)
        .filter(
            Expense.status == ExpenseStatus.SUBMITTED,
            Expense.submitted_at.isnot(None),
            Expense.submitted_at < cutoff,
            ~db.query(AgentNodeRun.id)
            .filter(
                AgentNodeRun.expense_id == Expense.id,
                AgentNodeRun.started_at >= cutoff,
            )
            .exists(),
        )
        .all()
    )
    return [row[0] for row in rows]


@worker_ready.connect
def resubmit_stuck_reviews(sender=None, **kwargs):
    """
    worker启动自愈：扫描并重派卡死单（resume=True——已完成节点复用输出，秒级通过）。
    历史bug（任务未注册即被丢弃）留下的死单由此自动恢复；幂等且秒级。
    多worker并发启动时每个进程都会跑本扫描：已在队列/已被领取（在途）的单跳过，
    防止同一张卡死单被并发重派多份、被几个worker同时审。
    任何异常只记日志：扫描失败不能阻止worker正常启动干活。
    """
    try:
        from app.database import SessionLocal
        from app.tasks.queue_inspect import inflight_expense_ids
        from app.utils.helpers import utc_now

        db = SessionLocal()
        try:
            stuck = find_stuck_expense_ids(db, utc_now())
        finally:
            db.close()
        # 在途查询失败(None)时降级不去重：重派本身幂等，宁可多发不漏恢复
        inflight = inflight_expense_ids()
        if inflight and stuck:
            before = len(stuck)
            stuck = [eid for eid in stuck if eid not in inflight]
            if len(stuck) < before:
                logger.info("worker启动自愈：%s张已在队列/执行中，跳过重派", before - len(stuck))
        for expense_id in stuck:
            try:
                run_ai_review.delay(expense_id, resume=True)
            except Exception as e:
                logger.exception("worker启动自愈：重派报销单#%s失败: %s", expense_id, e)
        if stuck:
            logger.info("worker启动自愈：已重派%s张卡死单 %s", len(stuck), stuck)
    except Exception as e:
        logger.exception("worker启动自愈扫描失败（不影响worker运行）: %s", e)
