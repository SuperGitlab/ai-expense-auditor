"""
报表服务
汇总统计、月度趋势、分类占比（finance/admin）
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Category, Expense, ExpenseItem, ExpenseStatus
from app.utils.cache import cache_get_or_set
from app.utils.helpers import decimal_to_float

logger = logging.getLogger(__name__)


def _month_expr():
    """
    按月分组的SQL表达式（按数据库方言选择）：
    - MySQL: DATE_FORMAT(created_at, '%Y-%m')
    - PostgreSQL: TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM')
    （to_char/date_trunc是PG函数，MySQL没有——切库时会崩）
    """
    if engine.dialect.name == "mysql":
        return func.date_format(Expense.created_at, "%Y-%m")
    return func.to_char(func.date_trunc("month", Expense.created_at), "YYYY-MM")


def get_summary(db: Session) -> dict:
    """总览统计：总数/各状态/总金额/平均风险分/本月数（缓存60秒）"""
    def build() -> dict:
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total = db.query(func.count(Expense.id)).scalar() or 0
        total_amount = db.query(
            func.coalesce(func.sum(Expense.total_amount), 0)
        ).filter(Expense.status != ExpenseStatus.CANCELLED).scalar()

        status_rows = (
            db.query(Expense.status, func.count(Expense.id))
            .group_by(Expense.status)
            .all()
        )
        avg_risk = db.query(
            func.coalesce(func.avg(Expense.risk_score), 0)
        ).filter(Expense.risk_score.isnot(None)).scalar()

        month_count = (
            db.query(func.count(Expense.id))
            .filter(Expense.created_at >= month_start)
            .scalar() or 0
        )

        return decimal_to_float({
            "total": total,
            "total_amount": total_amount,
            "by_status": {s.value if hasattr(s, "value") else str(s): c for s, c in status_rows},
            "avg_risk_score": round(float(avg_risk), 2),
            "month_count": month_count,
            "generated_at": now.isoformat(),
        })

    return cache_get_or_set("report:summary", build, ttl=60)


def get_trends(db: Session, months: int = 6) -> dict:
    """月度趋势：近N个月提交量与金额（缓存60秒）"""
    def build() -> dict:
        since = date.today().replace(day=1) - timedelta(days=30 * (months - 1))
        month = _month_expr()
        rows = (
            db.query(
                month.label("month"),
                func.count(Expense.id),
                func.coalesce(func.sum(Expense.total_amount), 0),
            )
            .filter(
                Expense.created_at >= since,
                Expense.status != ExpenseStatus.CANCELLED,
            )
            .group_by(month)
            .order_by(month)
            .all()
        )
        return {
            "months": [
                {"month": m, "count": int(c), "amount": float(a)} for m, c, a in rows
            ]
        }

    return cache_get_or_set(f"report:trends:{months}", build, ttl=60)


def get_by_category(db: Session) -> dict:
    """分类占比：各类别报销额与笔数（缓存60秒）"""
    def build() -> dict:
        rows = (
            db.query(
                Category.name,
                func.coalesce(func.sum(ExpenseItem.amount), 0),
                func.count(ExpenseItem.id),
            )
            .join(ExpenseItem, ExpenseItem.category_id == Category.id)
            .join(Expense, ExpenseItem.expense_id == Expense.id)
            .filter(Expense.status != ExpenseStatus.CANCELLED)
            .group_by(Category.name)
            .order_by(func.sum(ExpenseItem.amount).desc())
            .all()
        )
        total = sum(float(a) for _, a, _ in rows) or 1
        return {
            "categories": [
                {
                    "name": name,
                    "amount": float(amount),
                    "count": int(count),
                    "ratio": round(float(amount) / total, 4),
                }
                for name, amount, count in rows
            ]
        }

    return cache_get_or_set("report:by_category", build, ttl=60)


def export_report(db: Session, months: int = 6) -> bytes:
    """
    导出报表Excel：总览/月度趋势/分类占比/报销明细 四个sheet
    """
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    summary = get_summary(db)
    trends = get_trends(db, months)
    by_category = get_by_category(db)

    wb = Workbook()
    header_font = Font(bold=True)

    def _style(ws):
        for cell in ws[1]:
            cell.font = header_font
        ws.freeze_panes = "A2"

    # Sheet1 总览
    ws = wb.active
    ws.title = "总览"
    ws.append(["指标", "数值"])
    ws.append(["报销单总数", summary["total"]])
    ws.append(["累计报销金额", summary["total_amount"]])
    ws.append(["平均风险分", summary["avg_risk_score"]])
    ws.append(["本月新增", summary["month_count"]])
    ws.append(["生成时间", summary["generated_at"]])
    _style(ws)

    # Sheet2 月度趋势
    ws = wb.create_sheet("月度趋势")
    ws.append(["月份", "单数", "金额"])
    for m in trends["months"]:
        ws.append([m["month"], m["count"], m["amount"]])
    _style(ws)

    # Sheet3 分类占比
    ws = wb.create_sheet("分类占比")
    ws.append(["类别", "金额", "笔数", "占比"])
    for c in by_category["categories"]:
        ws.append([c["name"], c["amount"], c["count"], c["ratio"]])
    _style(ws)

    # Sheet4 报销明细
    ws = wb.create_sheet("报销明细")
    ws.append(["报销单号", "申请人", "部门", "类型", "金额", "状态", "风险分", "提交时间", "通过时间"])
    for e in db.query(Expense).order_by(Expense.created_at.desc()).all():
        ws.append([
            e.expense_no,
            e.applicant_name,
            e.applicant_department,
            e.expense_type.value if e.expense_type else "",
            float(e.total_amount),
            e.status.value if e.status else "",
            float(e.risk_score) if e.risk_score is not None else None,
            e.submitted_at.strftime("%Y-%m-%d %H:%M") if e.submitted_at else None,
            e.approved_at.strftime("%Y-%m-%d %H:%M") if e.approved_at else None,
        ])
    _style(ws)

    # 列宽：按各列内容最大长度粗略自适应（CJK按2倍宽）
    for sheet in wb.worksheets:
        for col_idx, col in enumerate(sheet.columns, start=1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            sheet.column_dimensions[get_column_letter(col_idx)].width = min(width * 2 + 2, 60)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
