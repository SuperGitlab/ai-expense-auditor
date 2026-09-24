"""
worker启动自愈扫描测试：find_stuck_expense_ids + worker_ready处理器
卡死单 = SUBMITTED 且提交时间超过宽限期，且宽限期内无任何节点进展（有进展=在跑）
MySQL DATETIME读回为naive，造数/断言统一用naive UTC
"""
from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from app.models import AgentNodeRun, Expense, ExpenseStatus
from app.utils.helpers import utc_now

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "自愈扫描测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
        }
    ],
}


def _naive(dt) -> object:
    """MySQL读回naive：比较前统一去掉tzinfo"""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _submitted_expense(client, username: str) -> int:
    """建单并提交（=SUBMITTED），返回id"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    assert client.post(f"/api/expenses/{expense_id}/submit", headers=headers).status_code == 200
    return expense_id


def _age_expense(db, expense_id: int, minutes: int):
    """把提交时间拨回N分钟前（模拟早已提交却无人处理）"""
    expense = db.get(Expense, expense_id)
    expense.submitted_at = _naive(utc_now() - timedelta(minutes=minutes))
    db.commit()


def _seed_node_run(db, expense_id: int, started_minutes_ago: int):
    db.add(AgentNodeRun(
        expense_id=expense_id, node="document", status="succeeded",
        started_at=_naive(utc_now() - timedelta(minutes=started_minutes_ago)),
        finished_at=_naive(utc_now() - timedelta(minutes=max(started_minutes_ago - 1, 0))),
    ))
    db.commit()


@requires_db
def test_finds_submitted_without_any_node_rows(client, db_session):
    """20分钟前提交、无任何节点行（任务从未被worker执行）→ 选中重派"""
    from app.tasks.review import find_stuck_expense_ids

    expense_id = _submitted_expense(client, "sweep_e1")
    _age_expense(db_session, expense_id, minutes=20)

    ids = find_stuck_expense_ids(db_session, utc_now())

    assert ids == [expense_id]


@requires_db
def test_skips_when_recent_node_progress(client, db_session):
    """节点1分钟前有进展（AI正在跑）→ 不选"""
    from app.tasks.review import find_stuck_expense_ids

    expense_id = _submitted_expense(client, "sweep_e2")
    _age_expense(db_session, expense_id, minutes=20)
    _seed_node_run(db_session, expense_id, started_minutes_ago=1)

    ids = find_stuck_expense_ids(db_session, utc_now())

    assert ids == []


@requires_db
def test_selects_when_node_rows_are_stale(client, db_session):
    """有节点行但也是15分钟前的（worker已死）→ 选中"""
    from app.tasks.review import find_stuck_expense_ids

    expense_id = _submitted_expense(client, "sweep_e3")
    _age_expense(db_session, expense_id, minutes=30)
    _seed_node_run(db_session, expense_id, started_minutes_ago=16)

    ids = find_stuck_expense_ids(db_session, utc_now())

    assert ids == [expense_id]


@requires_db
def test_ignores_pending_and_terminal(client, db_session):
    """PENDING（失败兜底已入人工队列）与终态不自动重派（防LLM重试风暴）"""
    from app.tasks.review import find_stuck_expense_ids

    pending_id = _submitted_expense(client, "sweep_e4")
    _age_expense(db_session, pending_id, minutes=20)
    db_session.get(Expense, pending_id).status = ExpenseStatus.PENDING

    approved_id = _submitted_expense(client, "sweep_e5")
    _age_expense(db_session, approved_id, minutes=20)
    db_session.get(Expense, approved_id).status = ExpenseStatus.APPROVED
    db_session.commit()

    ids = find_stuck_expense_ids(db_session, utc_now())

    assert ids == []


@requires_db
def test_handler_dispatches_resume(client, db_session, db_engine, monkeypatch):
    """worker_ready处理器：扫描并派发 resume=True；卡死单重派、活跃单不动"""
    import app.database as database_module
    import app.tasks.queue_inspect as queue_inspect_module
    import app.tasks.review as review_module

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    # 固定在途集合为空：避免本机真Redis里恰好有同id消息时误跳过（测试与broker解耦）
    monkeypatch.setattr(queue_inspect_module, "inflight_expense_ids", lambda: set())

    dispatched: list = []

    class _StubTask:
        def delay(self, expense_id, resume=False):
            dispatched.append((expense_id, resume))

    monkeypatch.setattr(review_module, "run_ai_review", _StubTask())

    stuck_id = _submitted_expense(client, "sweep_e6")
    _age_expense(db_session, stuck_id, minutes=20)
    active_id = _submitted_expense(client, "sweep_e7")
    _age_expense(db_session, active_id, minutes=20)
    _seed_node_run(db_session, active_id, started_minutes_ago=1)

    review_module.resubmit_stuck_reviews()  # 直接调（worker_ready信号在测试中不触发）

    assert dispatched == [(stuck_id, True)]


@requires_db
def test_handler_skips_inflight_duplicates(client, db_session, db_engine, monkeypatch):
    """多worker并发启动防重复派发：卡死单的消息已在队列/已被领取（在途）→ 不再重派"""
    import app.database as database_module
    import app.tasks.queue_inspect as queue_inspect_module
    import app.tasks.review as review_module

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database_module, "SessionLocal", factory)

    stuck_id = _submitted_expense(client, "sweep_e8")
    _age_expense(db_session, stuck_id, minutes=20)

    dispatched: list = []

    class _StubTask:
        def delay(self, expense_id, resume=False):
            dispatched.append((expense_id, resume))

    monkeypatch.setattr(review_module, "run_ai_review", _StubTask())
    monkeypatch.setattr(
        queue_inspect_module, "inflight_expense_ids", lambda: {stuck_id}
    )  # 模拟另一worker先启动已把它派进队列

    review_module.resubmit_stuck_reviews()

    assert dispatched == []  # 在途不重复派发
