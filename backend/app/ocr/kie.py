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


# ---------- 报销明细五字段抽取（上传发票自动回填用） ----------

# 旧版专票票头 "No 01096036"（:后是发票代码，须截断）
_RE_NO_PREFIX = re.compile(r"No\.?\s*(\d{8,20})")
_RE_YEN = re.compile(r"[¥￥]([\d,]+(?:\.\d+)?)")

# 费用类别关键词（对齐种子六类，按优先级先后；"酒"易误伤"酒店"故不入餐饮关键词）
_CATEGORY_RULES = [
    ("差旅费", ("机票", "火车", "航空", "客运", "差旅", "动车")),
    ("餐饮费", ("餐", "宴", "食品")),
    ("住宿费", ("住宿", "酒店", "宾馆")),
    ("市内交通费", ("出租", "网约", "滴滴", "公交", "地铁")),
    ("办公用品费", ("办公", "耗材", "设备", "纸张", "文具")),
]


def _normalize_date(raw: str) -> str:
    """'2018年08月07日'/'2018-8-7' → 'YYYY-MM-DD'；不合法返回空串"""
    m = re.search(r"(20\d{2})\s*[年-]\s*(\d{1,2})\s*[月-]\s*(\d{1,2})日?", raw)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def extract_item_fields(text: str) -> dict:
    """OCR全文 → 报销明细五字段（英文键）；缺失为空串，绝不编造"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    d = {"invoice_no": "", "expense_date": "", "amount": "",
         "description": "", "category_name": ""}

    # 发票号：发票号码: → No前缀 → 单独成行的8-20位纯数字
    for pat in (_RE_INVOICE_NO, _RE_NO_PREFIX):
        if m := pat.search(text):
            d["invoice_no"] = m.group(1)
            break
    if not d["invoice_no"]:
        d["invoice_no"] = next((ln for ln in lines if re.fullmatch(r"\d{8,20}", ln)), "")

    # 日期：复用KIE日期正则后归一化为表单格式
    if m := _RE_DATE.search(text):
        d["expense_date"] = _normalize_date(m.group(1))

    # 金额：价税合计行之后4行内的 ¥金额（大写/税号行可能穿插）；兜底取全文最大¥值
    for i, ln in enumerate(lines):
        if "价税合计" in ln:
            if m := _RE_YEN.search(" ".join(lines[i:i + 4])):
                d["amount"] = _clean_amount(m.group(1))
                break
    if not d["amount"]:
        if amts := _RE_YEN.findall(text):
            d["amount"] = _clean_amount(max(amts, key=lambda s: float(_clean_amount(s))))

    # 费用说明：*纯中文品类*货物名 明细行（密码区乱码行品类段非纯中文，天然排除）
    for ln in lines:
        if m := re.match(r"\*([一-龥]+)\*(.+)", ln):
            d["description"] = m.group(2).strip()
            break

    # 类别：全文关键词归类
    for cat, kws in _CATEGORY_RULES:
        if any(k in text for k in kws):
            d["category_name"] = cat
            break
    else:
        d["category_name"] = "其他费用"
    return d
