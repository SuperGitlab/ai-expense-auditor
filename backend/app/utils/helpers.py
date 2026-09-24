"""
通用工具函数
单号生成、分页、Decimal序列化等
"""
import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Sequence, Tuple


def generate_expense_no() -> str:
    """
    生成报销单号：EXP-YYYYMMDD-XXXXXXXX（8位随机大写字母数字）
    """
    date_part = date.today().strftime("%Y%m%d")
    rand_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"EXP-{date_part}-{rand_part}"


def paginate(items: Sequence[Any], total: int, page: int, page_size: int) -> dict:
    """
    构造分页响应结构

    Returns:
        dict: {items, total, page, page_size, total_pages}
    """
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": list(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def decimal_to_float(value: Any) -> Any:
    """Decimal转float（递归处理dict/list），避免JSON序列化报错"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: decimal_to_float(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [decimal_to_float(v) for v in value]
    return value


def utc_now() -> datetime:
    """当前UTC时间（带时区）"""
    return datetime.now(timezone.utc)
