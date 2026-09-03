"""
数据校验工具
发票号、文件扩展名、金额校验
"""
import re
from decimal import Decimal
from pathlib import Path

from app.config import settings

# 发票号：8-20位数字或大写字母（兼容增值税发票20位号码）
INVOICE_NO_PATTERN = re.compile(r"^[0-9A-Z]{8,20}$")


def validate_invoice_no(invoice_no: str | None) -> bool:
    """发票号格式校验"""
    if not invoice_no:
        return False
    return bool(INVOICE_NO_PATTERN.match(invoice_no.strip().upper()))


def validate_file_extension(filename: str) -> bool:
    """文件扩展名校验（对照配置的允许列表）"""
    ext = Path(filename).suffix.lower()
    return ext in [e.lower() for e in settings.ALLOWED_EXTENSIONS]


def validate_file_size(size: int) -> bool:
    """文件大小校验"""
    return 0 < size <= settings.MAX_FILE_SIZE


def validate_amount(amount: Decimal | float | int | str | None) -> bool:
    """金额校验：正数且不超过12位精度上限"""
    try:
        value = Decimal(str(amount))
        return Decimal("0.01") <= value <= Decimal("9999999999.99")
    except Exception:
        return False
