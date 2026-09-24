"""
制度文档规则抽取Celery任务（异步化：LLM抽取1-5分钟，不能让用户同步干等、不敢关窗口）
上传文件由API端点落盘，任务按路径读取并在结束时删除；
结果存Redis result backend（1小时），完成/失败均发站内通知。
"""
import logging
from pathlib import Path

from app.tasks import celery_app

logger = logging.getLogger(__name__)


def run_document_extraction(db, upload_path: str, filename: str) -> dict:
    """解析+LLM抽取+章节切分+草稿标注 → ExtractionDraftResponse形字典（纯编排，可单测）"""
    from app.services import rule_import_service as svc

    path = Path(upload_path)
    try:
        text, method = svc.read_document_text(path)
        if len(text.strip()) < svc.MIN_DOC_TEXT_CHARS:
            raise ValueError("未解析出有效文本（扫描件请确认清晰度，或改用文字版文档）")
        if len(text) > svc.MAX_TEXT_CHARS:
            raise ValueError(f"文档文本超长（{len(text)}字符，上限{svc.MAX_TEXT_CHARS}）")

        existing_codes, category_map = svc.load_import_context(db)
        try:
            drafts = svc.extract_rules_from_text(text, sorted(category_map))
        except svc.LLMExtractionError as e:
            raise ValueError(f"规则抽取失败，请重试: {e}") from e

        sections = svc.split_sections(text, fallback_title=filename)
        rules = svc.annotate_draft_rows(drafts.rules, existing_codes, category_map)
        return {
            "filename": filename,
            "source": filename,
            "sections": sections,
            "rules": [r.model_dump() for r in rules],
            "stats": {
                "text_chars": len(text),
                "method": method,
                "sections": len(sections),
                "rules": len(rules),
            },
        }
    finally:
        path.unlink(missing_ok=True)


@celery_app.task(name="rule_import.extract_document")
def extract_document_task(upload_path: str, filename: str, user_id: int) -> dict:
    """后台执行文档抽取；完成/失败都通知发起人（用户可随时关掉导入对话框，无需盯守）"""
    from app.database import SessionLocal
    from app.services.notification_service import send_notification

    db = SessionLocal()
    try:
        try:
            draft = run_document_extraction(db, upload_path, filename)
        except Exception as e:
            logger.warning("制度文档后台解析失败（《%s》）: %s", filename, e)
            send_notification(
                db, user_id, "制度文档解析失败",
                f"《{filename}》解析失败：{e}。可重新上传重试。", "rule_import",
            )
            raise
        send_notification(
            db, user_id, "制度文档解析完成",
            f"《{filename}》已抽出 {draft['stats']['rules']} 条草稿规则，"
            "请到 规则管理 → 导入规则 → 文档导入 核对并确认入库。", "rule_import",
        )
        return draft
    finally:
        db.close()
