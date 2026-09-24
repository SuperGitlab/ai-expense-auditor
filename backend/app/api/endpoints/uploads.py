"""
发票文件上传接口
multipart上传 → 扩展名/大小校验 → 落盘 {UPLOAD_DIR}/{yyyy}/{mm}/{uuid}{ext}
/ocr变体：落盘后RapidOCR识别票面，返回报销明细五字段回填信息（识别失败降级为普通上传）
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.deps import CurrentUser, DBSession
from app.config import settings
from app.models import Category
from app.ocr import kie, rapidocr_provider
from app.tools import ocr_tool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["文件上传"])


async def _save_upload(file: UploadFile) -> tuple[str, str, bytes]:
    """校验扩展名/大小并落盘，返回 (url, ext, content)；不合法抛HTTPException(400)"""
    ext = Path(file.filename or "").suffix.lower()
    allowed = [e.lower() for e in settings.ALLOWED_EXTENSIONS]
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext or '(无扩展名)'}，允许：{' '.join(allowed)}",
        )

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件超过大小限制 {settings.MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    now = datetime.now()
    rel_dir = Path(str(now.year)) / f"{now.month:02d}"
    target_dir = Path(settings.UPLOAD_DIR) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (target_dir / name).write_bytes(content)
    return f"/uploads/{rel_dir.as_posix()}/{name}", ext, content


@router.post("", status_code=201)
async def upload_invoice(file: UploadFile, current_user: CurrentUser):
    """上传发票文件，返回可访问的相对URL"""
    url, _ext, content = await _save_upload(file)
    return {"url": url, "filename": file.filename, "size": len(content)}


@router.post("/ocr", status_code=201)
async def upload_invoice_ocr(file: UploadFile, current_user: CurrentUser, db: DBSession):
    """
    上传发票并识别票面，返回五字段回填信息（中文键）+category_id。
    图片/PDF走RapidOCR（PDF由provider内部逐页转图），docx直读文字；
    识别失败降级为普通上传（fields=null），不影响文件落盘。
    """
    url, ext, content = await _save_upload(file)
    fields = None
    try:
        path = Path(settings.UPLOAD_DIR) / url[len("/uploads/"):]
        text = ocr_tool._read_docx(path) if ext == ".docx" else rapidocr_provider.run_ocr(path)[0]
        f = kie.extract_item_fields(text)
        # 识别出的类别名匹配启用中的类别 → 回填下拉框用的category_id
        cat = db.query(Category).filter(
            Category.name == f["category_name"], Category.is_active == True  # noqa: E712
        ).first()
        fields = {
            "发票号": f["invoice_no"],
            "费用日期": f["expense_date"],
            "金额(元)": f["amount"],
            "费用说明": f["description"],
            "费用类别": f["category_name"],
            "category_id": cat.id if cat else None,
        }
    except Exception as e:
        logger.warning("上传OCR识别失败，降级为普通上传 [%s]: %s", url, e)
    return {"url": url, "filename": file.filename, "size": len(content), "fields": fields}
