"""
v2 幂等迁移：两级审批链
1) expenses.status 枚举追加 manager_approved
2) approvals 表新增 step 列（可重复执行，已存在则跳过）
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
