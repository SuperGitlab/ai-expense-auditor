"""
ocr_tool接入测试
txt/docx直读+KIE+校验；图片/PDF走pipeline；/uploads相对路径映射；缺失文件空串
"""
import base64

from app.config import settings
from app.tools.ocr_tool import format_ocr_result, read_invoice_ocr, read_invoice_text

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

GOOD_TEXT = (
    "发票号码：25617000000123456789\n"
    "开票日期：2026-08-15\n"
    "合 计 ¥95.00 ¥5.00\n"
    "价税合计（大写）壹佰元整 ¥100.00\n"
)


def _write_docx(path, text):
    from docx import Document
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    doc.save(str(path))


def test_txt_direct_read_with_kie(tmp_path):
    p = tmp_path / "inv.txt"
    p.write_text(GOOD_TEXT, encoding="utf-8")
    r = read_invoice_ocr(str(p))
    assert r.method == "text"
    assert r.fields["invoice_no"] == "25617000000123456789"
    assert r.anomalies == []
    text = read_invoice_text(str(p))
    assert "【抽取字段】" in text and "【校验异常】" not in text


def test_docx_direct_read(tmp_path):
    p = tmp_path / "inv.docx"
    _write_docx(p, GOOD_TEXT)
    r = read_invoice_ocr(str(p))
    assert r.method == "text"  # docx跳过OCR层，同文本直读路径
    assert r.fields["amount_total"] == "100.00"


def test_bad_reconciliation_reports(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text(GOOD_TEXT.replace("¥5.00", "¥6.00"), encoding="utf-8")
    text = read_invoice_text(str(p))
    assert "【校验异常】" in text and "勾稽不符" in text


def test_image_routes_pipeline(tmp_path, monkeypatch):
    from app.ocr import pipeline
    from app.ocr.types import OCRResult
    captured = {}

    def _fake_extract(path, declared_no=None):
        captured["path"] = str(path)
        return OCRResult(method="rapidocr", raw_text="票面文本",
                         confidence=0.9, fields={"invoice_no": "12345678"},
                         anomalies=["勾稽不符: 1+2 != 3"])

    monkeypatch.setattr(pipeline, "extract_invoice", _fake_extract)
    p = tmp_path / "inv.png"
    p.write_bytes(PNG_1PX)
    r = read_invoice_ocr(str(p))
    assert r.method == "rapidocr"
    assert captured["path"] == str(p)
    assert "勾稽不符" in read_invoice_text(str(p))


def test_uploads_url_maps_to_local(tmp_path, monkeypatch):
    """invoice_url 存的是 /uploads/yyyy/mm/x.png 相对路径 → 映射 UPLOAD_DIR"""
    from app.ocr import pipeline
    from app.ocr.types import OCRResult
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        pipeline, "extract_invoice",
        lambda p, declared_no=None: OCRResult(method="rapidocr", raw_text="ok"),
    )
    local = tmp_path / "2026" / "09"
    local.mkdir(parents=True)
    (local / "abc.png").write_bytes(PNG_1PX)
    r = read_invoice_ocr("/uploads/2026/09/abc.png")
    assert r is not None and r.raw_text == "ok"


def test_missing_file_returns_none(tmp_path):
    assert read_invoice_ocr(str(tmp_path / "nope.png")) is None
    assert read_invoice_text(str(tmp_path / "nope.png")) == ""


def test_empty_and_unsupported():
    assert read_invoice_ocr(None) is None
    assert read_invoice_ocr("") is None
    assert read_invoice_text("") == ""


def test_format_ocr_result():
    from app.ocr.types import OCRResult
    r = OCRResult(method="text", raw_text="原文", fields={"invoice_no": "1"},
                  anomalies=["异常A"])
    s = format_ocr_result(r)
    assert s.startswith("原文") and "【抽取字段】" in s and "【校验异常】异常A" in s
    assert format_ocr_result(OCRResult(raw_text="只有原文")) == "只有原文"
