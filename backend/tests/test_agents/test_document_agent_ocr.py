"""
DocumentAgent逐明细OCR收集测试
monkeypatch结构化LLM(走确定性兜底)与read_invoice_ocr
"""
import asyncio

from app.agents.document_agent import DocumentAgent
from app.ocr.types import OCRResult
from app.tools import ocr_tool

SNAPSHOT = {
    "expense": {
        "id": 1, "expense_no": "EXP-1", "title": "t", "total_amount": 100.0,
        "status": "submitted",
    },
    "items": [
        {"id": 11, "invoice_url": "/uploads/x.png", "invoice_no": None, "amount": 100.0},
        {"id": 12, "invoice_url": None, "invoice_no": "ABC", "amount": 0.0},
    ],
    "applicant": {"recent_90d_count": 0, "recent_90d_total": 0.0},
}


def test_collects_ocr_items(monkeypatch):
    async def _raise(prompt):
        raise RuntimeError("llm down")
    agent = DocumentAgent()
    monkeypatch.setattr(agent, "structured_chat", _raise)  # 走确定性兜底分支

    def _fake_read(source, declared_no=None):
        if source and "x.png" in source:
            return OCRResult(method="rapidocr", raw_text="票面",
                             fields={"invoice_no": "123"},
                             anomalies=["勾稽不符: 1+2 != 3"])
        return None

    monkeypatch.setattr(ocr_tool, "read_invoice_ocr", _fake_read)

    result = asyncio.run(agent.run({"expense": SNAPSHOT}))
    data = result.data
    # 明细11：OCR有结果
    assert data["ocr_items"][11] == {"verified": False, "anomalies": ["勾稽不符: 1+2 != 3"]}
    # 明细12：无invoice_url不提取
    assert 12 not in data["ocr_items"]
    # 拼装文本进入invoice_texts供LLM分析
    assert "【校验异常】" in data["invoice_texts"]["明细#11"]
