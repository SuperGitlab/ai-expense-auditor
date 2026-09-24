"""
OCR混合流水线编排
RapidOCR第一层 → 路由判定(平均置信度≥阈值 且 KIE关键字段齐全)
  ├─ 是 → KIE正则抽取
  └─ 否 → Kimi视觉模型端到端抽取
→ 确定性业务校验(validators)
降级链：rapidocr失败→VLM；VLM失败→占位；任何一层失败不影响调用方
"""
import logging
from pathlib import Path

from app.config import settings
from app.ocr import kie, validators
from app.ocr.rapidocr_provider import run_ocr
from app.ocr.types import OCRResult
from app.ocr.vlm_provider import extract_fields as vlm_extract

logger = logging.getLogger(__name__)


def extract_invoice(path: str | Path, declared_no: str | None = None,
                    declared_amount: str | float | None = None) -> OCRResult:
    """图片/PDF发票 → OCRResult（不抛异常）"""
    if settings.OCR_PROVIDER == "off":
        return OCRResult(anomalies=["OCR未启用(OCR_PROVIDER=off)"])

    text, confidence = "", 0.0
    try:
        text, confidence = run_ocr(path)
    except Exception as e:
        logger.warning("RapidOCR失败，降级VLM [%s]: %s", Path(path).name, e)

    # 第一路由：置信度够 → 先试KIE
    fields = kie.extract_fields(text) if confidence >= settings.OCR_MIN_CONFIDENCE else {}
    method = None
    if kie.key_fields_complete(fields):
        method = "rapidocr"
    else:
        # KIE不完整（低置信/字段缺）→ VLM兜底
        vlm_fields = vlm_extract(path)
        if vlm_fields:
            fields, method = vlm_fields, "vlm"
        elif text:
            method = "rapidocr"  # VLM失败但OCR出了字：用KIE部分字段，让校验层报缺失
        else:
            logger.warning("OCR与VLM均不可用 [%s]", Path(path).name)
            return OCRResult(anomalies=["OCR与VLM均不可用"])

    logger.info(
        "发票识别路由 [%s]: method=%s, 置信度=%.2f, 字段=%s",
        Path(path).name, method, confidence, list(fields.keys()) or "无",
    )
    anomalies = validators.validate_invoice(fields, declared_no, declared_amount)
    return OCRResult(
        method=method,
        raw_text=text,
        confidence=confidence,
        fields=fields,
        anomalies=anomalies,
    )
