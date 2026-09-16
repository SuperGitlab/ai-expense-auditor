"""
断点恢复测试：成功节点输出持久化到 agent_node_runs.output_json，
run(resume=True) 注入 checkpoint，_traced 见自身key已存在即跳过（不重调LLM）
"""
import asyncio
import contextlib
import json
from datetime import timedelta

from app.agents import workflow as wf
from app.models import AgentNodeRun, Expense, ExpenseStatus
from app.utils.helpers import utc_now

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "断点恢复测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-RESUME-001",
        }
    ],
}


class _CaptureGraph:
    """替身图：捕获收到的 init_state（验证checkpoint注入），返回auto_approve终态"""
    def __init__(self):
        self.init_state = None

    async def ainvoke(self, state, config=None):
        self.init_state = dict(state)
        return {
            "risk": {"risk_score": 20.0, "risk_level": "low", "factors": []},
            "decision": {"action": "auto_approve", "reason": "低风险单据", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {"invoice_verified": True, "anomalies": [], "summary": ""},
            "errors": [],
        }


def _setup(monkeypatch) -> _CaptureGraph:
    graph = _CaptureGraph()
    monkeypatch.setattr(wf.workflow, "app", graph)
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )
    return graph


def _make_submitted_expense(client, username: str) -> int:
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    return expense_id


def _seed_run(db, expense_id: int, node: str, status: str,
              output_json: str | None = None, error: str | None = None) -> AgentNodeRun:
    row = AgentNodeRun(
        expense_id=expense_id, node=node, status=status,
        started_at=utc_now() - timedelta(minutes=10),
        finished_at=utc_now() - timedelta(minutes=9) if status != "running" else None,
        output_json=output_json, error=error,
    )
    db.add(row)
    db.commit()
    return row


# ===== _traced：跳过与持久化 =====

@requires_db
def test_traced_skips_when_checkpoint_present(db_session, monkeypatch):
    """state里已有本节点输出（resume注入）→ 返回{}、fn不执行、不写轨迹行"""
    async def boom(state):  # 被调用即失败
        raise AssertionError("断点节点不应重跑")

    monkeypatch.setattr(wf, "_node_session", lambda: contextlib.nullcontext(db_session))
    wrapped = wf._traced("rule", boom)

    result = asyncio.run(wrapped({"expense_id": 999999, "rules": {"violations": []}}))

    assert result == {}
    assert db_session.query(AgentNodeRun).count() == 0  # 未重记埋点，画布保留原时间戳


@requires_db
def test_traced_persists_output_on_success(client, db_session, monkeypatch):
    """成功节点输出JSON落库，可round-trip（断点恢复数据源）"""
    expense_id = _make_submitted_expense(client, "resume_t2")
    monkeypatch.setattr(wf, "_node_session", lambda: contextlib.nullcontext(db_session))

    rules_out = {"violations": [{"code": "R1"}], "hard_blocked": False, "points": 10}

    async def fake_node(state):
        return {"rules": rules_out}

    wrapped = wf._traced("rule", fake_node)
    asyncio.run(wrapped({"expense_id": expense_id, "expense": {}}))

    row = db_session.query(AgentNodeRun).filter_by(expense_id=expense_id, node="rule").one()
    assert row.status == "succeeded"
    assert json.loads(row.output_json) == rules_out


def test_output_dump_guard():
    """超长输出放弃断点（TEXT 64KB守卫）：返回None而非截断的坏JSON"""
    huge = {"anomalies": ["x" * 60_001]}
    assert wf._dump_output(huge) is None
    assert wf._dump_output({"a": 1}) == '{"a": 1}'


# ===== run(resume=...)：注入与轨迹处理 =====

@requires_db
def test_run_resume_injects_checkpoints(client, db_session, monkeypatch):
    """resume=True：succeeded行的output_json注入init_state；failed行不注入；旧行保留"""
    graph = _setup(monkeypatch)
    expense_id = _make_submitted_expense(client, "resume_t3")
    _seed_run(db_session, expense_id, "document", "succeeded",
              output_json='{"summary": "上轮解析结果", "anomalies": []}')
    _seed_run(db_session, expense_id, "rule", "succeeded",
              output_json='{"violations": [], "hard_blocked": false, "points": 0}')
    _seed_run(db_session, expense_id, "rag", "failed", error="上轮检索失败")

    asyncio.run(wf.workflow.run(db_session, expense_id, resume=True))

    assert graph.init_state["document"]["summary"] == "上轮解析结果"
    assert "violations" in graph.init_state["rules"]
    assert "rag" not in graph.init_state                      # 失败节点不注入，续跑重执行
    # 旧行未删（resume不整轮清空）
    assert db_session.query(AgentNodeRun).filter_by(expense_id=expense_id).count() == 3


@requires_db
def test_run_fresh_deletes_old_rows(client, db_session, monkeypatch):
    """resume=False（默认）：整轮清空旧轨迹——锁定既有行为"""
    _setup(monkeypatch)
    expense_id = _make_submitted_expense(client, "resume_t4")
    _seed_run(db_session, expense_id, "document", "succeeded",
              output_json='{"summary": "旧"}')

    asyncio.run(wf.workflow.run(db_session, expense_id))

    assert db_session.query(AgentNodeRun).filter_by(expense_id=expense_id).count() == 0


@requires_db
def test_run_resume_marks_stale_running_failed(client, db_session, monkeypatch):
    """resume时遗留running行（worker中断）标failed：画布可停轮询、不留假执行中"""
    _setup(monkeypatch)
    expense_id = _make_submitted_expense(client, "resume_t5")
    stale = _seed_run(db_session, expense_id, "risk", "running")

    asyncio.run(wf.workflow.run(db_session, expense_id, resume=True))

    db_session.expire_all()
    row = db_session.get(AgentNodeRun, stale.id)
    assert row.status == "failed"
    assert "中断" in (row.error or "")
    assert row.finished_at is not None


@requires_db
def test_record_node_refreshes_started_at_on_rerun(client, db_session):
    """同一(expense,node)重跑：running态刷新started_at（续跑时长不失真、sweep判活准确）"""
    expense_id = _make_submitted_expense(client, "resume_t6")
    old_start = (utc_now() - timedelta(hours=1)).replace(tzinfo=None)  # MySQL DATETIME无时区
    row = AgentNodeRun(
        expense_id=expense_id, node="rag", status="succeeded",
        started_at=old_start, finished_at=utc_now() - timedelta(minutes=59),
        output_json='{"relevant_rules": []}',
    )
    db_session.add(row)
    db_session.commit()

    wf._record_node(db_session, expense_id, "rag", "running")

    db_session.expire_all()
    row = db_session.query(AgentNodeRun).filter_by(expense_id=expense_id, node="rag").one()
    assert row.started_at > old_start
    assert row.finished_at is None
    assert row.output_json is None      # 进入新一轮执行，旧checkpoint作废


@requires_db
def test_resume_lands_on_pending_expense(client, db_session, monkeypatch):
    """串联守卫放宽：失败兜底转PENDING的单，断点重跑后AI结果正常落库生效"""
    _setup(monkeypatch)
    expense_id = _make_submitted_expense(client, "resume_t7")
    _seed_run(db_session, expense_id, "document", "succeeded",
              output_json='{"summary": "上轮", "anomalies": []}')
    expense = db_session.get(Expense, expense_id)
    expense.status = ExpenseStatus.PENDING
    db_session.commit()

    asyncio.run(wf.workflow.run(db_session, expense_id, resume=True))

    db_session.expire_all()
    expense = db_session.get(Expense, expense_id)
    assert expense.status == ExpenseStatus.APPROVED
    assert float(expense.risk_score) == 20.0
