"""
Kimi视觉模型端到端抽取（复杂票面兜底）
图片base64 → VLM → JSON字段；任何失败返回None（pipeline降级）
"""
import base64
import json
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是发票信息抽取助手。仔细看这张发票图片，提取以下字段，"
    '严格返回JSON对象（不要markdown代码块）：{"invoice_no": "发票号码", '
    '"date": "开票日期(YYYY-MM-DD)", "amount_excl": "不含税金额(数字)", '
    '"tax": "税额(数字)", "amount_total": "价税合计(数字)", '
    '"buyer_tax_id": "购买方纳税人识别号", "seller_tax_id": "销售方纳税人识别号"}。'
    "字段值均为字符串；无法辨认的字段填空字符串，绝不编造。只返回JSON，不要其他文字。"
)


def _image_data_url(path: Path) -> str:
    """本地图片/PDF首页 → data URL（PDF取首页，多页票据极少见）"""
    if path.suffix.lower() == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        try:
            raw = doc[0].get_pixmap(dpi=150).tobytes("png")
            mime = "image/png"
        finally:
            doc.close()
    else:
        raw = path.read_bytes()
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _parse_json(content: str) -> dict | None:
    """容错解析：剥markdown fence；非dict/解析失败返回None"""
    s = content.strip()
    if s.count("```") >= 2:
        s = s.split("```")[1]
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _build_llm():
    """VLM客户端工厂：超时/重试与主链路LLM同源——无界挂起同样会拖死审核worker"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.VLM_MODEL_NAME,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
        # K3思考模型仅允许temperature=1，不传（默认1）
        # K3思考token计入上限：只出短JSON但推理不可控，2048留余量
        max_tokens=2048,
        reasoning_effort=settings.LLM_REASONING_EFFORT,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
    )


def extract_fields(path: str | Path) -> dict | None:
    """VLM抽取发票字段；失败返回None（调用方降级，不抛异常）"""
    try:
        from langchain_core.messages import HumanMessage

        llm = _build_llm()
        msg = HumanMessage(content=[
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": _image_data_url(Path(path))}},
        ])
        resp = llm.invoke([msg])
        return _parse_json(resp.content)
    except Exception as e:
        logger.warning("VLM抽取失败 [%s]: %s", Path(path).name, e)
        return None
