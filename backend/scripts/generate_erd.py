"""
数据库 ER 图生成脚本
读取 app/models 的 SQLAlchemy 元数据，生成 Mermaid erDiagram 写入 docs/erd.md
不连数据库、不动业务表，只产出一个 Markdown 文件

用法（在 backend/ 目录下）:
    uv run python scripts/generate_erd.py

生成后：VSCode 打开 docs/erd.md，按 Ctrl+Shift+V 预览
"""
import enum
import logging
import sys
import time
from pathlib import Path

# 将 backend/ 加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Enum as SaEnum  # noqa: E402

from app import models as models_pkg  # noqa: E402
from app.models import Base  # noqa: E402  # 导入即完成全部模型注册到 metadata

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "erd.md"

# 常见外键的关系语义（(父表, 子表) → 关系名），未命中的用列名去掉 _id 兜底
RELATION_LABELS = {
    ("users", "expenses"): "提交",
    ("users", "notifications"): "接收",
    ("users", "approvals"): "审批",
    ("expenses", "expense_items"): "包含明细",
    ("categories", "expense_items"): "归属类别",
    ("expenses", "approvals"): "审批记录",
    ("expenses", "agent_node_runs"): "AI节点执行",
    ("categories", "rules"): "约束类别",
}


def column_type(col) -> str:
    """列类型显示名：VARCHAR(50) → VARCHAR；SQLAlchemy Enum → 枚举类名"""
    if isinstance(col.type, SaEnum):
        if col.type.enum_class is not None:
            return col.type.enum_class.__name__
        return col.type.name or "Enum"
    return str(col.type).split("(")[0].strip() or "column"


def column_keys(col) -> str:
    """主键/外键/唯一键标记，Mermaid 语法如 ` PK`、` FK, UK`"""
    keys = []
    if col.primary_key:
        keys.append("PK")
    if col.foreign_keys:
        keys.append("FK")
    if col.unique and not col.primary_key:
        keys.append("UK")
    return (" " + ", ".join(keys)) if keys else ""


def attribute_line(col) -> str:
    """单列的 Mermaid 属性行：`    VARCHAR expense_no UK "报销单号"`"""
    parts = [column_type(col), col.name + column_keys(col)]
    if col.comment:
        parts.append('"%s"' % col.comment.replace('"', "'"))
    return "    " + " ".join(parts)


def entity_blocks() -> list:
    """每张表一个实体块，列出全部列"""
    blocks = []
    for table in Base.metadata.sorted_tables:
        attrs = [attribute_line(c) for c in table.columns]
        blocks.append("    %s {\n%s\n    }" % (table.name, "\n".join(attrs)))
    return blocks


def relationship_lines() -> list:
    """由外键推导关系线：一对一 / 一对多(可选) / 一对多(必须)"""
    lines = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            for fk in col.foreign_keys:
                parent = fk.column.table
                if col.primary_key:
                    card = "||--||"      # 主键即外键：一对一
                elif col.unique or col.nullable:
                    card = "||--o|"      # 唯一键或可空：一对零或一
                else:
                    card = "||--o{"      # 非空外键：一对多
                label = RELATION_LABELS.get(
                    (parent.name, table.name), col.name.removesuffix("_id") or "ref")
                lines.append('    %s %s %s : "%s"' % (parent.name, card, table.name, label))
    return lines


def enum_rows() -> list:
    """枚举取值表（app.models 导出的所有 Enum 类）"""
    rows = ["| 枚举 | 取值 |", "| --- | --- |"]
    for name, obj in sorted(vars(models_pkg).items()):
        if (isinstance(obj, type) and issubclass(obj, enum.Enum)
                and obj.__module__.startswith("app.")):
            rows.append("| %s | %s |" % (name, "、".join(m.value for m in obj)))
    return rows


def render() -> str:
    """拼装完整 Markdown 文档"""
    entities = entity_blocks()
    relations = relationship_lines()
    log.debug("ER图拼装完成，entities=%s, relations=%s", len(entities), len(relations))
    return "\n".join([
        "# 数据模型 ER 图（自动生成）",
        "",
        "> 由 `backend/scripts/generate_erd.py` 生成，请勿手改；模型变更后重新运行：",
        "> `cd backend && uv run python scripts/generate_erd.py`",
        "> VSCode 打开本文件后按 `Ctrl+Shift+V` 预览",
        "",
        "```mermaid",
        "erDiagram",
        *entities,
        "",
        *relations,
        "```",
        "",
        "## 枚举取值",
        "",
        *enum_rows(),
        "",
    ])


def main() -> None:
    start = time.perf_counter()
    log.info("ER图生成开始，tables=%s, 输出=%s", len(Base.metadata.tables), OUTPUT_PATH)
    try:
        content = render()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(content, encoding="utf-8")
        rel_count = sum(
            len(list(c.foreign_keys)) for t in Base.metadata.sorted_tables for c in t.columns)
        log.info("ER图生成完成，tables=%s, relations=%s, cost=%.1fms",
                 len(Base.metadata.tables), rel_count, (time.perf_counter() - start) * 1000)
    except Exception:
        log.exception("ER图生成系统异常，输出=%s", OUTPUT_PATH)
        raise


if __name__ == "__main__":
    main()
