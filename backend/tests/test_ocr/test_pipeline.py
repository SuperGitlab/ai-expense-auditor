"""
OCR混合流水线编排测试
路由判定(置信度+关键字段)、降级链、off开关、校验接入
"""
import pytest

from app.config import settings
from app.ocr import pipeline

SAMPLE_TEXT = "发票号码：25617000000123456789\n合 计 ¥95.00 ¥5.00\n价税合计 ¥100.00"
COMPLETE_FIELDS = {
    "invoice_no": "25617000000123456789", "date": "2026-08-15",
    "amount_excl": "95.00", "tax": "5.00", "amount_total": "100.00",
}


@pytest.fixture()
def img(tmp_path):
    p = tmp_path / "inv.png"
    p.write_bytes(b"\x89PNG fake")
    return p


def test_high_confidence_complete_routes_rapidocr(monkeypatch, img):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "hybrid")
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT, 0.95))
    r = pipeline.extract_invoice(img)
    assert r.method == "rapidocr"
    assert r.confidence == 0.95
    assert r.fields["invoice_no"] == "25617000000123456789"
    assert r.anomalies == []  # 样例票勾稽平衡


def test_low_confidence_routes_vlm(monkeypatch, img):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "hybrid")
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT, 0.3))
    monkeypatch.setattr(
        pipeline, "vlm_extract",
        lambda p: {**COMPLETE_FIELDS, "buyer_tax_id": "91320100123456789X"},
    )
    r = pipeline.extract_invoice(img)
    assert r.method == "vlm"
    assert r.fields["amount_total"] == "100.00"
    assert r.anomalies == []


def test_high_confidence_but_kie_incomplete_routes_vlm(monkeypatch, img):
    """置信度够但正则抽不全（缺价税合计行）→ 升级VLM"""
    monkeypatch.setattr(settings, "OCR_PROVIDER", "hybrid")
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: ("模糊票面文本", 0.9))
    monkeypatch.setattr(pipeline, "vlm_extract", lambda p: COMPLETE_FIELDS)
    r = pipeline.extract_invoice(img)
    assert r.method == "vlm"


def test_rapidocr_fails_and_vlm_fails_placeholder(monkeypatch, img):
    def _boom(p):
        raise RuntimeError("engine down")
    monkeypatch.setattr(pipeline, "run_ocr", _boom)
    monkeypatch.setattr(pipeline, "vlm_extract", lambda p: None)
    r = pipeline.extract_invoice(img)
    assert r.method == "placeholder"
    assert r.anomalies == ["OCR与VLM均不可用"]


def test_vlm_fails_low_confidence_keeps_rapidocr_text(monkeypatch, img):
    """低置信OCR出了字+VLM挂 → 保留rapidocr文本，校验补字段缺失异常"""
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT[:20], 0.5))
    monkeypatch.setattr(pipeline, "vlm_extract", lambda p: None)
    r = pipeline.extract_invoice(img)
    assert r.method == "rapidocr"
    assert r.raw_text == SAMPLE_TEXT[:20]
    assert any("缺失" in a or "勾稽" in a for a in r.anomalies)


def test_provider_off(monkeypatch, img):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "off")
    r = pipeline.extract_invoice(img)
    assert r.method == "placeholder"
    assert r.anomalies == ["OCR未启用(OCR_PROVIDER=off)"]


def test_validation_anomalies_attached(monkeypatch, img):
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (
        "发票号码：25617000000123456789\n合 计 ¥95.00 ¥6.00\n价税合计 ¥100.00", 0.95
    ))
    r = pipeline.extract_invoice(img)  # 95+6 != 100
    assert any("勾稽不符" in a for a in r.anomalies)
    assert r.ok is False


def test_declared_no_mismatch(monkeypatch, img):
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT, 0.95))
    r = pipeline.extract_invoice(img, declared_no="999")
    assert any("发票号不一致" in a for a in r.anomalies)
