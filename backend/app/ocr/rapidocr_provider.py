"""
RapidOCR封装（rapidocr-onnxruntime）
懒加载单例引擎；PDF经PyMuPDF逐页转图
本层失败直接抛异常——降级决策统一在pipeline做
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_engine = None  # 懒加载单例：模型加载约1s，进程内复用


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _pdf_to_images(path: Path) -> list[bytes]:
    """PDF逐页渲染为PNG字节流（150dpi足够票据OCR）"""
    import pymupdf
    doc = pymupdf.open(path)
    try:
        return [page.get_pixmap(dpi=150).tobytes("png") for page in doc]
    finally:
        doc.close()


def run_ocr(path: str | Path) -> tuple[str, float]:
    """
    图片/PDF → (全文文本, 平均置信度)
    引擎接受路径/bytes；rapidocr-onnxruntime自带方向处理
    """
    p = Path(path)
    pages = _pdf_to_images(p) if p.suffix.lower() == ".pdf" else [p.read_bytes()]
    engine = _get_engine()
    lines: list[str] = []
    scores: list[float] = []
    for img in pages:
        result, _elapse = engine(img)
        for _box, text, score in result or []:
            lines.append(text)
            scores.append(float(score))
    text = "\n".join(lines)
    confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
    return text, confidence
