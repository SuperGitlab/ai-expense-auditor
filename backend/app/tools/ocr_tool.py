"""
OCR工具
发票/单据文本与结构化提取：
- 文本类(.txt/.md/.csv)与.docx：直读文字，跳过OCR层，直接KIE抽取+业务校验
- 图片/PDF：走 app.ocr.pipeline 混合流水线(RapidOCR→KIE/VLM→校验)
- /uploads/* 相对URL映射到本地 UPLOAD_DIR
- http(s)：文本类直读；图片/PDF下载到临时文件后走流水线
read_invoice_text 签名不变（返回拼装文本供DocumentAgent分析）；
read_invoice_ocr 返回结构化 OCRResult（工作流回写用）。
"""
import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import settings
from app.ocr import kie, validators
from app.ocr.types import OCRResult

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def read_invoice_ocr(source: str | None, declared_no: str | None = None) -> OCRResult | None:
    """
    结构化提取发票信息。
    返回 OCRResult；文件缺失/类型不支持/提取失败返回 None（不抛异常）。
    """
    if not source:
        return None
    try:
        if source.startswith(("http://", "https://")):
            return _read_url_ocr(source, declared_no)
        if source.startswith("/uploads/"):
            return _extract_file(
                Path(settings.UPLOAD_DIR) / source[len("/uploads/"):], declared_no
            )
        return _extract_file(Path(source), declared_no)
    except Exception as e:
        logger.warning(f"单据结构化提取失败 [{source}]: {e}")
        return None


def read_invoice_text(source: str | None) -> str:
    """兼容入口（签名不变）：返回「原文+抽取字段+校验异常」拼装文本"""
    r = read_invoice_ocr(source)
    return format_ocr_result(r) if r is not None else ""


def format_ocr_result(r: OCRResult) -> str:
    """OCRResult → 给LLM分析的拼装文本"""
    parts = [r.raw_text]
    if r.fields:
        parts.append("【抽取字段】" + json.dumps(r.fields, ensure_ascii=False))
    if r.anomalies:
        parts.append("【校验异常】" + "；".join(r.anomalies))
    return "\n".join(p for p in parts if p)


# ---------- 内部分派 ----------

def _read_url_ocr(url: str, declared_no: str | None) -> OCRResult | None:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _result_from_text(_download_text(url), declared_no)
    if ext not in IMAGE_EXTENSIONS and ext != ".docx":
        return None
    # 图片/PDF/docx：下载到临时文件走统一分派
    suffix = ext or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(_download_bytes(url))
        tmp = Path(f.name)
    try:
        return _extract_file(tmp, declared_no)
    finally:
        tmp.unlink(missing_ok=True)


def _extract_file(p: Path, declared_no: str | None) -> OCRResult | None:
    if not p.exists():
        logger.warning(f"单据文件不存在: {p}")
        return None
    ext = p.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _result_from_text(p.read_text(encoding="utf-8", errors="ignore"), declared_no)
    if ext == ".docx":
        return _result_from_text(_read_docx(p), declared_no)
    if ext in IMAGE_EXTENSIONS:
        # 函数内import：每次调用取模块属性，测试monkeypatch pipeline.extract_invoice 才能生效
        from app.ocr.pipeline import extract_invoice
        return extract_invoice(p, declared_no)
    return None


def _read_docx(p: Path) -> str:
    from docx import Document
    doc = Document(str(p))
    return "\n".join(par.text for par in doc.paragraphs if par.text.strip())


def _result_from_text(text: str, declared_no: str | None) -> OCRResult:
    """文本直读（txt/docx）：跳过OCR层，直接KIE抽取+业务校验"""
    fields = kie.extract_fields(text)
    return OCRResult(
        method="text",
        raw_text=text,
        fields=fields,
        anomalies=validators.validate_invoice(fields, declared_no),
    )


def _download_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "expense-audit/1.0"})
    with urlopen(req, timeout=10) as resp:  # noqa: S310 白名单场景
        return resp.read().decode("utf-8", errors="ignore")


def _download_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "expense-audit/1.0"})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 白名单场景
        return resp.read()
