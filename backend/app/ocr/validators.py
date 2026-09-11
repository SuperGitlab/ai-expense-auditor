"""
增值税发票确定性业务校验（纯函数）
税号18/20位（统一社会信用代码，数字+大写字母）、不含税+税额=价税合计±0.01、
日期合法、发票号与手填一致
"""
import re
from datetime import datetime

# 统一社会信用代码：18或20位，数字+大写英文字母
_TAX_ID_RE = re.compile(r"[0-9A-Z]{18}|[0-9A-Z]{20}")


def validate_invoice_no(fields: dict, declared_no: str | None) -> list[str]:
    inv = str(fields.get("invoice_no") or "").strip()
    if not inv:
        return ["发票号码缺失"]
    if not inv.isdigit() or not (8 <= len(inv) <= 20):
        return [f"发票号码格式异常: {inv}"]
    declared = (declared_no or "").strip()
    if declared and inv != declared:
        return [f"发票号不一致: 票面{inv} vs 手填{declared}"]
    return []


def validate_tax_ids(fields: dict) -> list[str]:
    anomalies = []
    for side, key in (("购方", "buyer_tax_id"), ("销方", "seller_tax_id")):
        v = str(fields.get(key) or "").strip()
        if not v:
            continue  # 票面可能无，缺失不算异常（由KIE路由层控制完整性）
        if not _TAX_ID_RE.fullmatch(v):
            anomalies.append(f"{side}税号格式异常: {v}")
    return anomalies


def validate_amounts(fields: dict) -> list[str]:
    try:
        excl = float(fields["amount_excl"])
        tax = float(fields["tax"])
        total = float(fields["amount_total"])
    except (KeyError, TypeError, ValueError):
        return ["金额字段缺失或非法，无法勾稽核对"]
    if abs(excl + tax - total) > 0.01:
        return [f"勾稽不符: 不含税{excl} + 税额{tax} != 价税合计{total}"]
    return []


def validate_date(fields: dict) -> list[str]:
    raw = str(fields.get("date") or "").strip()
    if not raw:
        return []
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日"):
        try:
            datetime.strptime(raw, fmt)
            return []
        except ValueError:
            continue
    return [f"开票日期格式异常: {raw}"]


def validate_invoice(fields: dict, declared_no: str | None = None) -> list[str]:
    """全部业务校验，返回异常描述列表（空=全过）"""
    return (
        validate_invoice_no(fields, declared_no)
        + validate_tax_ids(fields)
        + validate_amounts(fields)
        + validate_date(fields)
    )
