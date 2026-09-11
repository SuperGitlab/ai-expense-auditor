"""
migrate_v2 幂等迁移测试：approvals.step 列存在、expenses.status 枚举含 manager_approved、
重复执行不报错（需测试DB）
"""
from sqlalchemy import inspect, text

from app.db_migrations import migrate_v2

from tests.conftest import requires_db


@requires_db
def test_migrate_v2_idempotent(db_session):
    engine = db_session.get_bind()
    migrate_v2(engine)   # 第二次执行不应报错（列已存在时跳过）
    migrate_v2(engine)

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("approvals")}
    assert "step" in cols

    # status 列类型已扩展（MySQL ENUM 文本含新值，且按 ORM 约定用大写 name）
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                 "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='expenses' "
                 "AND COLUMN_NAME='status'")
        ).scalar()
    assert "'MANAGER_APPROVED'" in row and "'DRAFT'" in row
