"""
OCR工具
发票/单据的文本提取（txt直读；图片/PDF预留OCR接口接入点）
"""
import logging
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# 支持直读的文本类扩展名
TEXT_EXTENSIONS = {".txt", ".md", ".csv"}


def read_invoice_text(source: str | None) -> str:
    """
    读取发票/单据文本内容

    Args:
        source: 本地文件路径或URL（报销明细里的invoice_url）

    Returns:
        str: 提取的文本；不可用时返回空串（不抛异常，由上层降级处理）
    """
    if not source:
        return ""
    try:
        if source.startswith(("http://", "https://")):
            return _read_url(source)
        return _read_local(source)
    except Exception as e:
        logger.warning(f"单据文本提取失败 [{source}]: {e}")
        return ""


def _read_url(url: str) -> str:
    """下载并读取URL内容（仅文本类；图片/PDF返回占位说明）"""
    path = urlparse(url).path.lower()
    ext = Path(path).suffix
    if ext in TEXT_EXTENSIONS:
        req = Request(url, headers={"User-Agent": "expense-audit/1.0"})
        with urlopen(req, timeout=10) as resp:  # noqa: S310 白名单场景
            return resp.read().decode("utf-8", errors="ignore")
    # 图片/PDF：预留OCR服务接入点
    return f"[{ext or '未知'}格式单据，需接入OCR服务提取内容]"


def _read_local(path: str) -> str:
    """读取本地文件（仅文本类；图片/PDF返回占位说明）"""
    p = Path(path)
    if not p.exists():
        logger.warning(f"单据文件不存在: {path}")
        return ""
    if p.suffix.lower() in TEXT_EXTENSIONS:
        return p.read_text(encoding="utf-8", errors="ignore")
    return f"[{p.suffix}格式单据，需接入OCR服务提取内容]"
