"""
db_migrations 幂等迁移测试
回归背景：migrate_v3 手写DDL漏了Base混入的created_at/updated_at，
测试库走create_all带上了两列全绿，开发库走迁移建表缺列→ORM查询1054、接口500
"""
from sqlalchemy import inspect, text

from app.db_migrations import migrate_v3
from app.models import AgentNodeRun

from tests.conftest import requires_db


@requires_db
def test_migrate_v3_ddl_covers_orm_columns(db_engine):
    """migrate_v3 建出的表列集必须覆盖ORM全部列；幂等重跑不报错"""
    with db_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS agent_node_runs"))

    migrate_v3(db_engine)  # 用迁移DDL真实建表
    migrate_v3(db_engine)  # 幂等重跑

    ddl_cols = {c["name"] for c in inspect(db_engine).get_columns("agent_node_runs")}
    orm_cols = {c.name for c in AgentNodeRun.__table__.columns}
    missing = orm_cols - ddl_cols
    assert not missing, f"migrate_v3 DDL缺列（ORM读写会1054）: {missing}"


@requires_db
def test_migrate_v3_repairs_legacy_table(db_engine):
    """旧版DDL建的缺列表：重跑migrate_v3能补齐created_at/updated_at"""
    with db_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS agent_node_runs"))
        # 复刻旧版缺列DDL（不含时间列）
        conn.execute(text("""
            CREATE TABLE agent_node_runs (
                id BIGINT NOT NULL AUTO_INCREMENT,
                expense_id BIGINT NOT NULL,
                node VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL,
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME NULL,
                detail VARCHAR(500) NULL,
                error VARCHAR(500) NULL,
                PRIMARY KEY (id),
                UNIQUE KEY uq_agent_node_runs_expense_node (expense_id, node)
            )
        """))

    migrate_v3(db_engine)  # CREATE TABLE IF NOT EXISTS跳过，走补列分支

    ddl_cols = {c["name"] for c in inspect(db_engine).get_columns("agent_node_runs")}
    assert {"created_at", "updated_at"} <= ddl_cols
