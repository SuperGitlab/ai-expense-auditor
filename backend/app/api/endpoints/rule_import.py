"""
规则导入接口（admin）
JSON直导（全量校验有错全拒，只写MySQL）+ 制度文档抽取草稿 + 确认入库（Rule表+Chroma）
"""
import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import DBSession, require_roles
from app.config import settings
from app.models import User, UserRole
from app.rag.vectorstore import is_available
from app.schemas.rule_import import (
    DocumentImportConfirmRequest,
    ExtractionDraftResponse,
    ImportResultResponse,
    RuleImportJsonRequest,
    RuleImportRowError,
    SectionOut,
)
from app.services import rule_import_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules/import", tags=["规则导入"])

# 管理员依赖（同rules.py）
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]

# 复用workflow模块级知识库单例（与RAG检索同一份库）；测试monkeypatch本模块属性
from app.agents.workflow import knowledge_base  # noqa: E402

ALLOWED_EXTS = {".docx", ".pdf"}
MIN_DOC_TEXT_CHARS = 30  # 解析文本低于此长度视为无效（扫描件识别失败）
MAX_SECTIONS_CHARS = 500_000  # 确认回传的章节总字符上限


def _row_errors_response(errors: list[RuleImportRowError]) -> JSONResponse:
    """400逐行错误明细（errors与detail平级：detail给toast，errors给前端错误表格）"""
    return JSONResponse(
        status_code=400,
        content={
            "detail": f"共{len(errors)}行校验失败，已全部拒绝（未写入任何数据）",
            "errors": [e.model_dump() for e in errors],
        },
    )


@router.post("/json", response_model=ImportResultResponse)
def import_rules_json(payload: RuleImportJsonRequest, db: DBSession, current_user: AdminUser):
    """JSON全量导入：任一行校验失败或code重复则整体拒绝；不碰Chroma"""
    try:
        rules = svc.import_json_rules(db, payload.rules)
    except svc.ImportValidationError as e:
        return _row_errors_response(e.errors)
    return ImportResultResponse(
        imported=len(rules),
        rules=rules,
        chroma_written=0,
        chroma_available=is_available(),
        cleared_policies=False,
    )


@router.post("/document/extract", response_model=ExtractionDraftResponse)
def extract_document(file: UploadFile, db: DBSession, current_user: AdminUser):
    """上传docx/pdf → 解析+章节切分+LLM抽取规则草稿（不写任何存储，预览确认两步式的第一步）

    同步def：FastAPI自动放线程池执行，OCR/LLM长调用不阻塞事件循环。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"仅支持 .docx/.pdf 文档，收到 {ext or '（无扩展名）'}")

    content = file.file.read()
    if not content:
        raise HTTPException(400, "文件为空")
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(400, f"文件超过 {settings.MAX_FILE_SIZE // 1048576}MB 限制")

    # 解析器按路径读文件：先落临时文件，用完即删
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        text, method = svc.read_document_text(tmp_path)
        if len(text.strip()) < MIN_DOC_TEXT_CHARS:
            raise HTTPException(422, "未解析出有效文本（扫描件请确认清晰度，或改用文字版文档）")
        if len(text) > svc.MAX_TEXT_CHARS:
            raise HTTPException(
                400, f"文档文本超长（{len(text)}字符，上限{svc.MAX_TEXT_CHARS}）"
            )

        existing_codes, category_map = svc.load_import_context(db)
        try:
            drafts = svc.extract_rules_from_text(text, sorted(category_map))
        except svc.LLMExtractionError as e:
            raise HTTPException(502, f"规则抽取失败，请重试: {e}")

        sections = svc.split_sections(text, fallback_title=file.filename or "正文")
        rules = svc.annotate_draft_rows(drafts.rules, existing_codes, category_map)
        return ExtractionDraftResponse(
            filename=file.filename or "document",
            source=file.filename or "公司财务制度",
            sections=[SectionOut(**s) for s in sections],
            rules=rules,
            stats={
                "text_chars": len(text),
                "method": method,
                "sections": len(sections),
                "rules": len(rules),
            },
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/document/confirm", response_model=ImportResultResponse)
def confirm_document(
    payload: DocumentImportConfirmRequest, db: DBSession, current_user: AdminUser
):
    """确认草稿入库：全量校验（有错全拒，Chroma不碰）→ Rule表 → Chroma(append/replace)

    rules可为空=仅导入制度原文入知识库；MySQL先落（规则是主数据），
    Chroma后落且失败不回滚（知识库可重新导入补齐）。
    """
    total_chars = sum(len(s.content) for s in payload.sections)
    if total_chars > MAX_SECTIONS_CHARS:
        raise HTTPException(400, f"原文章节内容过大（{total_chars}字符，上限{MAX_SECTIONS_CHARS}）")

    existing_codes, category_map = svc.load_import_context(db)
    parsed, row_errors = svc.validate_rule_rows(payload.rules, existing_codes, category_map)
    errors = [
        RuleImportRowError(
            index=i,
            code=str(payload.rules[i].get("code")) if payload.rules[i].get("code") else None,
            errors=errs,
        )
        for i, errs in enumerate(row_errors)
        if errs
    ]
    if errors:
        return _row_errors_response(errors)

    items = [p for p in parsed if p is not None]
    try:
        rules = svc.write_rules(db, items, category_map)
    except svc.ImportValidationError as e:
        return _row_errors_response(e.errors)

    try:
        added, cleared = knowledge_base.import_policy_document(
            [s.model_dump() for s in payload.sections],
            payload.source,
            replace=payload.mode == "replace",
        )
    except Exception as e:
        logger.error(f"制度原文入库知识库失败（规则已入库，可重新导入文档补齐知识库）: {e}")
        added, cleared = 0, False

    return ImportResultResponse(
        imported=len(rules),
        rules=rules,
        chroma_written=added,
        chroma_available=is_available(),
        cleared_policies=cleared,
    )
