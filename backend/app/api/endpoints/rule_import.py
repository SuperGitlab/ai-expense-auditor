"""
规则导入接口（admin）
JSON直导（全量校验有错全拒，只写MySQL）+ 制度文档抽取草稿 + 确认入库（Rule表+Milvus向量库）
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
    ExtractionStatusResponse,
    ExtractionSubmitResponse,
    ImportResultResponse,
    RuleImportJsonRequest,
    RuleImportRowError,
)
from app.services import rule_import_service as svc
from app.tasks import celery_app
from app.tasks.rule_extraction import extract_document_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules/import", tags=["规则导入"])

# 管理员依赖（同rules.py）
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]

# 复用workflow模块级知识库单例（与RAG检索同一份库）；测试monkeypatch本模块属性
from app.agents.workflow import knowledge_base  # noqa: E402

ALLOWED_EXTS = {".docx", ".pdf"}
MAX_SECTIONS_CHARS = 500_000  # 确认回传的章节总字符上限


def _row_errors_response(errors: list[RuleImportRowError], channel: str) -> JSONResponse:
    """400逐行错误明细（errors与detail平级：detail给toast，errors给前端错误表格）"""
    # 拒绝原因同步落服务端日志：控制台排障不再只看到一行400访问日志
    # （明细最多带10行防刷屏，完整逐行明细前端错误表格里有）
    lines = [f"第{e.index}行({e.code}): {'；'.join(e.errors)}" for e in errors]
    suffix = " …(其余%s行省略)" % (len(lines) - 10) if len(lines) > 10 else ""
    logger.warning(
        "规则导入整体拒绝[%s] 共%s行失败: %s%s",
        channel, len(errors), " | ".join(lines[:10]), suffix,
    )
    return JSONResponse(
        status_code=400,
        content={
            "detail": f"共{len(errors)}行校验失败，已全部拒绝（未写入任何数据）",
            "errors": [e.model_dump() for e in errors],
        },
    )


@router.post("/json", response_model=ImportResultResponse)
def import_rules_json(payload: RuleImportJsonRequest, db: DBSession, current_user: AdminUser):
    """JSON全量导入：任一行校验失败或code重复则整体拒绝；不碰向量库"""
    try:
        rules = svc.import_json_rules(db, payload.rules)
    except svc.ImportValidationError as e:
        return _row_errors_response(e.errors, "JSON直导")
    return ImportResultResponse(
        imported=len(rules),
        rules=rules,
        vector_written=0,
        vector_available=is_available(),
        cleared_policies=False,
    )


@router.post("/document/extract", response_model=ExtractionSubmitResponse)
def extract_document(file: UploadFile, current_user: AdminUser):
    """上传docx/pdf → 校验+落盘+派发后台抽取任务，毫秒级返回task_id

    LLM抽取1-5分钟：同步等会占死线程池线程、用户不敢关窗口。
    任务结果存Redis result backend（1小时），完成/失败均发站内通知；
    前端轮询 GET /document/extract/{task_id} 取回草稿，确认入库仍走 /document/confirm。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"仅支持 .docx/.pdf 文档，收到 {ext or '（无扩展名）'}")

    content = file.file.read()
    if not content:
        raise HTTPException(400, "文件为空")
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(400, f"文件超过 {settings.MAX_FILE_SIZE // 1048576}MB 限制")

    # 任务在worker进程按路径读文件：落临时盘（任务结束自行删除）
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        upload_path = str(tmp.name)
    task = extract_document_task.delay(upload_path, file.filename or "document", current_user.id)
    logger.info("制度文档抽取任务已派发: task=%s file=%s user=%s", task.id, file.filename, current_user.id)
    return ExtractionSubmitResponse(task_id=task.id, filename=file.filename or "document")


@router.get("/document/extract/{task_id}", response_model=ExtractionStatusResponse)
def extraction_status(task_id: str, current_user: AdminUser):
    """轮询抽取任务状态：SUCCESS携带完整草稿（章节+规则），FAILURE携带错误信息"""
    res = celery_app.AsyncResult(task_id)
    if res.state == "SUCCESS":
        return ExtractionStatusResponse(
            state="SUCCESS", draft=ExtractionDraftResponse.model_validate(res.result)
        )
    if res.state == "FAILURE":
        return ExtractionStatusResponse(state="FAILURE", error=str(res.result))
    return ExtractionStatusResponse(state=res.state)


@router.post("/document/confirm", response_model=ImportResultResponse)
def confirm_document(
    payload: DocumentImportConfirmRequest, db: DBSession, current_user: AdminUser
):
    """确认草稿入库：全量校验（有错全拒，向量库不碰）→ Rule表 → Milvus(append/replace)

    rules可为空=仅导入制度原文入知识库；MySQL先落（规则是主数据），
    向量库后落且失败不回滚（知识库可重新导入补齐）。
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
        return _row_errors_response(errors, "文档确认")

    items = [p for p in parsed if p is not None]
    try:
        rules = svc.write_rules(db, items, category_map)
    except svc.ImportValidationError as e:
        return _row_errors_response(e.errors, "文档确认·写入冲突")

    if settings.RAG_PROVIDER == "off":
        # RAG停用：规则已入MySQL（主数据），跳过向量库写入（不调嵌入接口不碰Milvus）
        logger.info("RAG未启用（RAG_PROVIDER=off），制度原文未入向量库")
        added, cleared = 0, False
    else:
        try:
            added, cleared = knowledge_base.import_policy_document(
                [s.model_dump() for s in payload.sections],
                payload.source,
                replace=payload.mode == "replace",
            )
        except Exception as e:
            logger.exception("制度原文入库知识库失败（规则已入库，可重新导入文档补齐知识库）: %s", e)
            added, cleared = 0, False

    return ImportResultResponse(
        imported=len(rules),
        rules=rules,
        vector_written=added,
        vector_available=is_available(),
        cleared_policies=cleared,
    )
