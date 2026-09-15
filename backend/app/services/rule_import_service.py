"""
规则导入服务
JSON直导与制度文档导入两通道共用的校验/解析/章节切分/LLM抽取/编排逻辑
"""
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Category, Rule
from app.ocr.rapidocr_provider import run_ocr
from app.schemas.rule_import import DraftRuleOut, RuleImportItem, RuleImportRowError

logger = logging.getLogger(__name__)

# 这两个操作符只判存在性，不需要阈值；其余操作符缺阈值=规则永远无法命中
NO_THRESHOLD_OPERATORS = {"exists", "not_exists"}
# 送入LLM抽取的文本上限（保护上下文与确认回传payload）
MAX_TEXT_CHARS = 100_000
# PDF文本层低于此长度视为扫描件，降级OCR
MIN_PDF_TEXT_CHARS = 200


class ImportValidationError(Exception):
    """全量校验失败（有错全拒）：携带逐行错误明细"""

    def __init__(self, errors: list[RuleImportRowError]):
        self.errors = errors
        super().__init__(f"{len(errors)}行校验失败")


class LLMExtractionError(Exception):
    """LLM规则抽取失败（端点转502请重试）"""


# ---------- 行校验（纯函数，无DB） ----------

def validate_rule_rows(
    raw_rows: list[dict], existing_codes: set[str], category_map: dict[str, int]
) -> tuple[list, list[list[str]]]:
    """
    逐行校验（库内code集合与类别映射由调用方先查好传入，本函数无DB）

    Returns: (解析结果, 行错误) 两个与入参等长的平行列表；
             非法行的解析结果为None，错误列表为空=该行合法
    """
    parsed: list = []
    row_errors: list[list[str]] = []
    seen_codes: set[str] = set()

    for raw in raw_rows:
        errors: list[str] = []
        item = None

        # 1) schema级校验（长度/枚举/范围），违规转带字段名的行错误
        try:
            item = RuleImportItem.model_validate(raw)
        except ValidationError as e:
            for err in e.errors():
                field = ".".join(str(loc) for loc in err["loc"])
                errors.append(f"字段{field}校验失败: {err['msg']}")

        if item is not None:
            # 2) code库内重复 / 批内重复
            if item.code in existing_codes:
                errors.append(f"规则代码 {item.code} 已存在")
            if item.code in seen_codes:
                errors.append(f"规则代码 {item.code} 在本次导入中重复")
            else:
                seen_codes.add(item.code)
            # 3) category_code有效性（错误附可用列表便于修正）
            if item.category_code is not None and item.category_code not in category_map:
                errors.append(
                    f"类别代码 {item.category_code} 不存在，可用: "
                    f"{', '.join(sorted(category_map)) or '（无）'}"
                )
            # 4) 可比操作符必须带阈值
            if item.operator not in NO_THRESHOLD_OPERATORS and not (item.threshold or "").strip():
                errors.append(f"操作符 {item.operator.value} 需要提供threshold阈值")

        parsed.append(item)
        row_errors.append(errors)

    return parsed, row_errors


# ---------- 章节切分（纯函数，无DB） ----------

# 标题行样式：第X章/节/条/款/部分、一、二、（一）、"1. "；标题本身≤40字
_HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百千\d]+[章节条款部分]"
    r"|[一二三四五六七八九十]+[、.．]"
    r"|[（(][一二三四五六七八九十\d]+[)）]"
    r"|\d{1,3}[、.．]\s)"
    r".{0,40}$"
)


def split_sections(text: str, fallback_title: str = "正文") -> list[dict]:
    """
    制度原文按标题行切章节

    无任何标题时整篇作一节（标题取fallback_title，通常为文件名）。
    非标题行原文逐字保留——进Chroma的制度文本不允许被改写（保真），
    所以章节划分用正则启发式而非让LLM转述。
    """
    sections: list[dict] = []
    current = {"title": fallback_title, "lines": []}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped and _HEADING_RE.match(stripped):
            if current["lines"]:
                sections.append(
                    {"title": current["title"], "content": "\n".join(current["lines"])}
                )
            # 标题行同时进content首行：每一行原文都在节内逐字保留（保真），
            # 且标题关键词随正文一起被向量化（检索按章节语义命中更准）
            current = {"title": stripped, "lines": [stripped]}
        elif stripped:
            current["lines"].append(stripped)

    if current["lines"]:
        sections.append({"title": current["title"], "content": "\n".join(current["lines"])})
    return sections


# ---------- 文档解析 ----------

def read_document_text(path: Path) -> tuple[str, str]:
    """读取制度文档文本 → (text, method)；pdf文本层过短（扫描件）降级OCR"""
    if path.suffix.lower() == ".docx":
        return _read_docx_full(path), "docx"
    text = _read_pdf_text(path)
    if len(text.strip()) >= MIN_PDF_TEXT_CHARS:
        return text, "pdf_text"
    ocr_text, _conf = run_ocr(path)
    return ocr_text or "", "pdf_ocr"


def _read_docx_full(path: Path) -> str:
    """按文档顺序读段落+表格（表格单元格用｜连接）

    制度文档常把标准写进表格（如"级别｜住宿上限"），ocr_tool._read_docx
    只读段落会丢表格，这里按body子元素顺序完整读取。
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    lines: list[str] = []
    for block in doc.element.body.iterchildren():
        if block.tag.endswith("}p"):
            text = Paragraph(block, doc).text.strip()
            if text:
                lines.append(text)
        elif block.tag.endswith("}tbl"):
            for row in Table(block, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    lines.append("｜".join(cells))
    return "\n".join(lines)


def _read_pdf_text(path: Path) -> str:
    """pymupdf文本层直提（原生PDF；扫描件文本层近空由调用方降级OCR）"""
    import pymupdf

    doc = pymupdf.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ---------- LLM抽取 ----------

class ExtractedRule(RuleImportItem):
    """LLM抽取的规则草稿行（quote=支撑该规则的原文片段）"""
    quote: str = Field("", description="支撑该规则的原文片段（逐字复制）")


class ExtractedRules(BaseModel):
    rules: list[ExtractedRule] = Field(default_factory=list)


_EXTRACTION_PROMPT = """你是财务制度规则抽取助手。从制度文本中抽取可量化、可机判的报销审核规则。

字段要求：
- name: 简短中文名；code: 大写前缀_数字风格（如 HOTEL_LIMIT_600）
- field_name 只能取: amount(明细金额) / total_amount(单据总额) / expense_date(费用日期) / invoice_no(发票号) / description(明细说明)
- operator: gt大于 / lt小于 / gte大于等于 / lte小于等于 / eq等于 / in集合(阈值逗号分隔) / exists存在 / not_exists缺失
- rule_type: amount_limit金额限制 / invoice_required发票要求 / date_limit超期(阈值填天数) / duplicate_invoice重复发票 / category_restrict类别限制 / custom自定义
- severity: block自动驳回 / warn计风险分 / review转人工
- threshold: 字符串；exists/not_exists可留空，其余必填
- category_code: 只能从可用列表中选，无法判断留空
- risk_points: 0-100，按违规严重程度估
- quote: 支撑该规则的原文片段，必须从制度文本中逐字复制

只抽有明确判定标准（数字/天数/必填项）的条款，最多60条，宁缺毋滥。

可用费用类别code: {category_codes}

制度文本：
{text}"""


def extract_rules_from_text(text: str, category_codes: list[str]) -> ExtractedRules:
    """LLM结构化抽取规则草稿；失败抛LLMExtractionError（端点转502请重试）

    GLM兼容接口不支持response_format，必须走function_calling模式
    （同base_agent._make_structured_llm惯例；service层无需继承BaseAgent）
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.MODEL_NAME,
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_API_BASE,
        temperature=0,
        max_tokens=8192,
    ).with_structured_output(ExtractedRules, method="function_calling")
    prompt = _EXTRACTION_PROMPT.format(
        category_codes=", ".join(category_codes) or "（无）", text=text
    )
    try:
        result = llm.invoke([HumanMessage(content=prompt)])
    except Exception as e:
        logger.warning(f"制度规则抽取失败: {e}")
        raise LLMExtractionError(str(e)) from e
    if not isinstance(result, ExtractedRules):
        raise LLMExtractionError(f"抽取结果类型异常: {type(result)}")
    return result


def annotate_draft_rows(
    drafts: list[ExtractedRule], existing_codes: set[str], category_map: dict[str, int]
) -> list[DraftRuleOut]:
    """草稿轻校验：schema已由结构化输出保证，这里做语义检查标到issues[]（不抛错，人工预览时核对）"""
    out: list[DraftRuleOut] = []
    seen: set[str] = set()
    for d in drafts:
        issues: list[str] = []
        if d.code in existing_codes:
            issues.append(f"规则代码 {d.code} 已存在（导入前需改名或先删旧规则）")
        if d.code in seen:
            issues.append(f"规则代码 {d.code} 在本批草稿中重复")
        else:
            seen.add(d.code)
        if d.category_code and d.category_code not in category_map:
            issues.append(
                f"类别代码 {d.category_code} 不存在，可用: "
                f"{', '.join(sorted(category_map)) or '（无）'}（请人工指定）"
            )
        if d.operator not in NO_THRESHOLD_OPERATORS and not (d.threshold or "").strip():
            issues.append(f"操作符 {d.operator} 缺少阈值")
        out.append(DraftRuleOut(**d.model_dump(), issues=issues))
    return out


# ---------- DB编排 ----------

def load_import_context(db: Session) -> tuple[set[str], dict[str, int]]:
    """(库内全部规则code, 启用中类别code→id)——校验所需DB上下文一次查齐"""
    codes = {c for (c,) in db.query(Rule.code).all()}
    category_map = {
        code: cid
        for code, cid in db.query(Category.code, Category.id)
        .filter(Category.is_active == True)  # noqa: E712
        .all()
    }
    return codes, category_map


def to_rule_row(item: RuleImportItem, category_map: dict[str, int]) -> dict:
    """导入行 → Rule(**row) 字段（category_code优先解析成category_id）"""
    data = item.model_dump(exclude={"category_code"})
    if item.category_code is not None:
        data["category_id"] = category_map.get(item.category_code)
    return data


def write_rules(db: Session, items: list[RuleImportItem], category_map: dict[str, int]) -> list[Rule]:
    """批量写入（单事务；并发撞unique索引回滚转导入校验异常）"""
    rules = [Rule(**to_rule_row(item, category_map)) for item in items]
    try:
        db.add_all(rules)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ImportValidationError(
            [RuleImportRowError(index=0, errors=[f"规则代码冲突（可能与其他导入并发），请重试: {e.orig}"])]
        ) from e
    for r in rules:
        db.refresh(r)
    return rules


def import_json_rules(db: Session, raw_rows: list[dict]) -> list[Rule]:
    """JSON直导编排：全量校验有错全拒，否则批量入库（不碰Chroma）"""
    existing_codes, category_map = load_import_context(db)
    parsed, row_errors = validate_rule_rows(raw_rows, existing_codes, category_map)
    errors = [
        RuleImportRowError(
            index=i,
            code=str(raw_rows[i].get("code")) if raw_rows[i].get("code") else None,
            errors=errs,
        )
        for i, errs in enumerate(row_errors)
        if errs
    ]
    if errors:
        raise ImportValidationError(errors)
    return write_rules(db, [p for p in parsed if p is not None], category_map)
