"""
RapidOCR封装测试
懒加载引擎可替换；PDF分派；任何异常向上抛（由pipeline降级）
"""
import base64

import pytest

from app.ocr import rapidocr_provider

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _FakeEngine:
    """固定输出：两行文本带不同置信度"""
    def __call__(self, img):
        assert img is not None
        return (
            [
                ([[0, 0], [10, 0], [10, 10], [0, 10]], "发票号码:12345678", 0.9),
                ([[0, 0], [10, 0], [10, 10], [0, 10]], "价税合计 ¥100.00", 0.8),
            ],
            0.1,
        )


def test_run_ocr_image(monkeypatch, tmp_path):
    monkeypatch.setattr(rapidocr_provider, "_get_engine", lambda: _FakeEngine())
    p = tmp_path / "inv.png"
    p.write_bytes(PNG_1PX)
    text, confidence = rapidocr_provider.run_ocr(p)
    assert "发票号码:12345678" in text and "价税合计" in text
    assert confidence == pytest.approx(0.85)  # (0.9+0.8)/2


def test_run_ocr_empty_result(monkeypatch, tmp_path):
    class _Empty:
        def __call__(self, img):
            return None, 0.1
    monkeypatch.setattr(rapidocr_provider, "_get_engine", lambda: _Empty())
    p = tmp_path / "blank.png"
    p.write_bytes(PNG_1PX)
    assert rapidocr_provider.run_ocr(p) == ("", 0.0)


def test_missing_file_raises(tmp_path):
    """文件不存在：异常向上抛（pipeline捕获降级），不静默"""
    with pytest.raises(Exception):
        rapidocr_provider.run_ocr(tmp_path / "nope.png")


@pytest.mark.llm
def test_real_rapidocr_reads_digits(tmp_path):
    """真实引擎：opencv画数字图片应被识别（标记llm默认跳过）"""
    import cv2
    import numpy as np
    img = np.full((80, 400), 255, dtype=np.uint8)
    cv2.putText(img, "12345678", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
    p = tmp_path / "real.png"
    cv2.imwrite(str(p), img)
    text, confidence = rapidocr_provider.run_ocr(p)
    assert "12345678" in text.replace(" ", "")
    assert confidence > 0.5
