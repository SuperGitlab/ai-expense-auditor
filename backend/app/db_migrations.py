"""
v2 幂等迁移：两级审批链
1) expenses.status 枚举追加 manager_approved
2) approvals 表新增 step 列（可重复执行，已存在则跳过）
v3 幂等迁移：agent_node_runs 节点轨迹表（工作流画布/人工接管观测）
v4 幂等迁移：agent_node_runs 补 output_json 列（断点恢复checkpoint）
项目未用 Alembic，手动 DDL；新库经 init_db.py 建表即为新结构，无需本模块
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.models.expense import ExpenseStatus

logger = logging.getLogger(__name__)

# SQLAlchemy Enum(枚举类) 默认按成员 name（大写）存库，
# DDL 必须用 name 而非 value，否则 MySQL 读回值与 ORM 查表不一致
_STATUS_VALUES = tuple(e.name for e in ExpenseStatus)


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {"t": table, "c": column}).scalar()
    return bool(row)


def migrate_v2(engine: Engine) -> None:
    """幂等执行 v2 迁移（本项目 dev/test 均为 MySQL）"""
    if engine.dialect.name != "mysql":
        raise NotImplementedError(
            f"migrate_v2 仅支持 MySQL（当前方言: {engine.dialect.name}）；"
            "其他方言请重建库后走 init_db.py"
        )
    with engine.begin() as conn:
        # 1) expenses.status 追加 manager_approved（MODIFY 全量重写枚举，重复执行无害）
        values = ", ".join(f"'{v}'" for v in _STATUS_VALUES)
        conn.execute(text(
            f"ALTER TABLE expenses MODIFY status ENUM({values}) NOT NULL "
            "COMMENT '报销状态'"
        ))

        # 2) approvals.step 列（已存在则跳过）
        if not _column_exists(conn, "approvals", "step"):
            conn.execute(text(
                "ALTER TABLE approvals ADD COLUMN step VARCHAR(20) NULL "
                "COMMENT '审批层级: manager/finance'"
            ))
    logger.info("migrate_v2 完成（expenses.status + approvals.step）")


def migrate_v3(engine: Engine) -> None:
    """幂等执行 v3 迁移：建 agent_node_runs 节点轨迹表（工作流画布）
    注意：Base 混入 created_at/updated_at 通用列，手写 DDL 必须带上；
    旧版 DDL 漏过这两列（表已建好的环境靠下面的补列修复）
    """
    if engine.dialect.name != "mysql":
        raise NotImplementedError(
            f"migrate_v3 仅支持 MySQL（当前方言: {engine.dialect.name}）；"
            "其他方言请重建库后走 init_db.py"
        )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_node_runs (
                id BIGINT NOT NULL AUTO_INCREMENT,
                expense_id BIGINT NOT NULL COMMENT '报销单ID',
                node VARCHAR(20) NOT NULL COMMENT '节点名: document/rule/rag/risk/decision',
                status VARCHAR(20) NOT NULL COMMENT '状态: running/succeeded/failed/overridden',
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '开始时间',
                finished_at DATETIME NULL COMMENT '结束时间',
                detail VARCHAR(500) NULL COMMENT '结果摘要',
                error VARCHAR(500) NULL COMMENT '失败原因',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                updated_at DATETIME NULL COMMENT '更新时间',
                PRIMARY KEY (id),
                UNIQUE KEY uq_agent_node_runs_expense_node (expense_id, node),
                CONSTRAINT fk_agent_node_runs_expense FOREIGN KEY (expense_id)
                    REFERENCES expenses (id)
            )
        """))
        # 已用旧版DDL建过表的环境：补齐Base通用时间列（幂等，已存在则跳过）
        if not _column_exists(conn, "agent_node_runs", "created_at"):
            conn.execute(text(
                "ALTER TABLE agent_node_runs ADD COLUMN created_at DATETIME "
                "NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'"
            ))
        if not _column_exists(conn, "agent_node_runs", "updated_at"):
            conn.execute(text(
                "ALTER TABLE agent_node_runs ADD COLUMN updated_at DATETIME NULL "
                "COMMENT '更新时间'"
            ))
    logger.info("migrate_v3 完成（agent_node_runs 节点轨迹表）")


def migrate_v4(engine: Engine) -> None:
    """幂等执行 v4 迁移：agent_node_runs 补 output_json 列（断点恢复checkpoint）
    成功节点的输出JSON持久化于此，断点续跑时直接复用、不重调LLM
    """
    if engine.dialect.name != "mysql":
        raise NotImplementedError(
            f"migrate_v4 仅支持 MySQL（当前方言: {engine.dialect.name}）；"
            "其他方言请重建库后走 init_db.py"
        )
    with engine.begin() as conn:
        if not _column_exists(conn, "agent_node_runs", "output_json"):
            conn.execute(text(
                "ALTER TABLE agent_node_runs ADD COLUMN output_json TEXT NULL "
                "COMMENT '成功节点输出JSON（断点续跑checkpoint）'"
            ))
    logger.info("migrate_v4 完成（agent_node_runs.output_json 断点checkpoint列）")
