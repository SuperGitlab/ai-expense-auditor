"""
增值税发票字段正则抽取（KIE, Key Information Extraction）——纯函数
输入RapidOCR/docx直读的全文文本，输出结构化字段dict
票面布局多变，只做保守抽取：匹配不到的字段缺失，由路由层决定是否升级VLM
"""
import re

_RE_INVOICE_NO = re.compile(r"发票号码[:：]?\s*(\d{8,20})")
_RE_DATE = re.compile(
    r"开票日期[:：]?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{1,2}-\d{1,2})"
)
# 合计行：合计 ¥95.00 ¥5.00（不含税金额、税额并排）
_RE_SUBTOTAL = re.compile(
    r"合\s*计\s*[¥￥]?\s*([0-9,]+\.\d{2})\s*[¥￥]?\s*([0-9,]+\.\d{2})"
)
# 价税合计行：价税合计（大写） 壹佰元整 ¥100.00
_RE_TOTAL = re.compile(r"价税合计[^0-9¥￥]{0,20}[¥￥]?\s*([0-9,]+\.\d{2})")
# 税号：购销方各一，按出现顺序取
_RE_TAX_ID = re.compile(r"纳税人识别号[:：]?\s*([0-9A-Z]{15,20})")

# 路由判定的关键字段：齐了才走KIE分支，缺任一升级VLM
KEY_FIELDS = ("invoice_no", "amount_total")


def _clean_amount(s: str) -> str:
    return s.replace(",", "")


def extract_fields(text: str) -> dict:
    """从全文文本抽取发票字段，抽取不到的键缺失"""
    fields: dict = {}
    if m := _RE_INVOICE_NO.search(text):
        fields["invoice_no"] = m.group(1)
    if m := _RE_DATE.search(text):
        fields["date"] = re.sub(r"\s+", "", m.group(1))
    if m := _RE_SUBTOTAL.search(text):
        fields["amount_excl"] = _clean_amount(m.group(1))
        fields["tax"] = _clean_amount(m.group(2))
    if m := _RE_TOTAL.search(text):
        fields["amount_total"] = _clean_amount(m.group(1))
    ids = _RE_TAX_ID.findall(text)
    if len(ids) >= 1:
        fields["buyer_tax_id"] = ids[0]
    if len(ids) >= 2:
        fields["seller_tax_id"] = ids[1]
    return fields


def key_fields_complete(fields: dict) -> bool:
    """路由用：关键字段（发票号+价税合计）是否齐全"""
    return all(fields.get(k) for k in KEY_FIELDS)
