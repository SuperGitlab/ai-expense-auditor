"""
Celery任务测试（直接调用任务函数=内联执行任务体，不起worker/broker）
"""
from sqlalchemy.orm import sessionmaker

from app.models import Expense, ExpenseStatus

from tests.conftest import register_and_login, requires_db


class _FakeWorkflow:
    """假工作流：记录调用（含resume参数）；配置了异常则在run时抛出"""

    def __init__(self, exc: Exception | None = None):
        self.calls = []
        self._exc = exc

    async def run(self, db, expense_id, *, resume=False):
        self.calls.append((expense_id, resume))
        if self._exc:
            raise self._exc
        return {}


def _create_expense(client) -> int:
    """建一张报销单并提交（SUBMITTED），返回id（真实链路中任务只在提交后派发）"""
    headers = register_and_login(client, "task_r1")
    resp = client.post(
        "/api/expenses",
        json={
            "title": "任务测试",
            "expense_type": "travel",
            "items": [
                {
                    "category_id": 1,
                    "description": "测试明细",
                    "amount": "100.00",
                    "expense_date": "2026-08-20",
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text
    return expense_id


def _setup(monkeypatch, db_engine, fake):
    """把任务体内的两个惰性import目标换成测试替身：workflow→假对象、SessionLocal→测试库工厂"""
    import app.agents.workflow as wf
    import app.database as database_module

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    monkeypatch.setattr(wf, "workflow", fake)
    return factory


@requires_db
def test_task_runs_workflow(client, db_session, db_engine, monkeypatch):
    """任务体执行工作流并返回reviewed结果"""
    from app.tasks.review import run_ai_review

    fake = _FakeWorkflow()
    _setup(monkeypatch, db_engine, fake)

    expense_id = _create_expense(client)
    result = run_ai_review(expense_id)  # 直接调用=内联执行（.delay才走broker）

    assert fake.calls == [(expense_id, False)]
    assert result == f"expense#{expense_id} reviewed"


@requires_db
def test_task_passes_resume_flag(client, db_session, db_engine, monkeypatch):
    """resume=True（断点续跑）透传给workflow.run"""
    from app.tasks.review import run_ai_review

    fake = _FakeWorkflow()
    _setup(monkeypatch, db_engine, fake)

    expense_id = _create_expense(client)
    run_ai_review(expense_id, resume=True)

    assert fake.calls == [(expense_id, True)]


@requires_db
def test_task_fallback_pending(client, db_session, db_engine, monkeypatch):
    """工作流抛异常：任务不抛出，单据保守转PENDING人工"""
    from app.tasks.review import run_ai_review

    factory = _setup(monkeypatch, db_engine, _FakeWorkflow(exc=RuntimeError("boom")))

    expense_id = _create_expense(client)
    result = run_ai_review(expense_id)

    assert "fallback_to_pending" in result
    with factory() as check:
        exp = check.query(Expense).filter(Expense.id == expense_id).one()
        assert exp.status == ExpenseStatus.PENDING


@requires_db
def test_task_failure_keeps_human_decision(client, db_session, db_engine, monkeypatch):
    """人审优先：人工已把单据流转为REJECTED后任务失败兜底，不再掰成PENDING"""
    from app.tasks.review import run_ai_review

    factory = _setup(monkeypatch, db_engine, _FakeWorkflow(exc=RuntimeError("boom")))

    expense_id = _create_expense(client)
    with factory() as s:
        exp = s.query(Expense).filter(Expense.id == expense_id).one()
        exp.status = ExpenseStatus.REJECTED
        s.commit()

    result = run_ai_review(expense_id)

    assert "fallback_to_pending" in result  # 任务自身仍不抛
    with factory() as check:
        exp = check.query(Expense).filter(Expense.id == expense_id).one()
        assert exp.status == ExpenseStatus.REJECTED  # 人的裁决不被兜底覆盖
