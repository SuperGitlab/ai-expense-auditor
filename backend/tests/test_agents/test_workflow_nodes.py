"""
_traced 节点埋点单测：running→succeeded/failed 生命周期、摘要与错误落库
（_node_session 替换为测试会话；expense_id 用真实单据——轨迹表有外键约束）
"""
import asyncio
import contextlib

from app.agents import workflow as wf
from app.models import AgentNodeRun

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "节点埋点测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-NODE-001",
        }
   ],
}


def _use_test_session(monkeypatch, db_session):
    """节点轨迹短会话指向测试会话（nullcontext：不关共享会话）"""
    monkeypatch.setattr(wf, "_node_session", lambda: contextlib.nullcontext(db_session))


def _make_expense(client, username: str) -> int:
    """建一张真实报销单，返回其id（轨迹表expense_id有FK约束）"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@requires_db
def test_traced_records_running_then_succeeded(client, db_session, monkeypatch):
    """节点正常完成：先running后succeeded，带摘要、带起止时间"""
    _use_test_session(monkeypatch, db_session)
    expense_id = _make_expense(client, "node_e1")

    async def risk_fn(state):
        return {"risk": {"risk_score": 35.0, "risk_level": "low", "factors": []}}

    result = asyncio.run(wf._traced("risk", risk_fn)({"expense_id": expense_id, "expense": {}}))
    assert result["risk"]["risk_score"] == 35.0  # 原样透传节点返回

    run = db_session.query(AgentNodeRun).filter_by(expense_id=expense_id, node="risk").one()
    assert run.status == "succeeded"
    assert "35" in (run.detail or "") and "low" in (run.detail or "")
    assert run.error is None
    assert run.started_at is not None and run.finished_at is not None


@requires_db
def test_traced_records_running_entry(client, db_session, monkeypatch):
    """进入节点即写running行（画布轮询实时可见）"""
    _use_test_session(monkeypatch, db_session)
    expense_id = _make_expense(client, "node_e2")
    calls = []

    async def hang_fn(state):
        calls.append(db_session.query(AgentNodeRun).filter_by(
            expense_id=expense_id, node="document").one().status)
        return {"document": {"anomalies": [], "summary": ""}}

    asyncio.run(wf._traced("document", hang_fn)({"expense_id": expense_id, "expense": {}}))
    assert calls == ["running"]  # 节点执行中途查到的是running

    run = db_session.query(AgentNodeRun).filter_by(expense_id=expense_id, node="document").one()
    assert run.status == "succeeded" and run.finished_at is not None


@requires_db
def test_traced_marks_failed_when_node_degrades(client, db_session, monkeypatch):
    """节点自身降级（返回errors非空）：记failed+首条错误，不抛异常"""
    _use_test_session(monkeypatch, db_session)
    expense_id = _make_expense(client, "node_e3")

    async def degraded_fn(state):
        return {"rag": {"relevant_rules": [], "similar_cases": []},
                "errors": ["RAG检索节点失败: embedding超时"]}

    asyncio.run(wf._traced("rag", degraded_fn)({"expense_id": expense_id, "expense": {}}))
    run = db_session.query(AgentNodeRun).filter_by(expense_id=expense_id, node="rag").one()
    assert run.status == "failed"
    assert "RAG检索节点失败" in (run.error or "")


@requires_db
def test_traced_marks_failed_and_reraises(client, db_session, monkeypatch):
    """节点抛异常：记failed后re-raise（外层兜底：Celery任务失败转PENDING）"""
    _use_test_session(monkeypatch, db_session)
    expense_id = _make_expense(client, "node_e4")

    async def boom_fn(state):
        raise RuntimeError("graph infra崩了")

    import pytest
    with pytest.raises(RuntimeError):
        asyncio.run(wf._traced("decision", boom_fn)({"expense_id": expense_id, "expense": {}}))
    run = db_session.query(AgentNodeRun).filter_by(expense_id=expense_id, node="decision").one()
    assert run.status == "failed"
    assert "graph infra" in (run.error or "")
