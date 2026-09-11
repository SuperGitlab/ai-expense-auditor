"""
发票文件上传接口
multipart上传 → 扩展名/大小校验 → 落盘 {UPLOAD_DIR}/{yyyy}/{mm}/{uuid}{ext}
"""
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.deps import CurrentUser
from app.config import settings

router = APIRouter(prefix="/api/uploads", tags=["文件上传"])


@router.post("", status_code=201)
async def upload_invoice(file: UploadFile, current_user: CurrentUser):
    """上传发票文件，返回可访问的相对URL"""
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

    return {
        "url": f"/uploads/{rel_dir.as_posix()}/{name}",
        "filename": file.filename,
        "size": len(content),
    }
