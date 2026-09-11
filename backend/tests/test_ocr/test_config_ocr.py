"""
OCR相关配置默认值测试
不依赖DB/env（_env_file=None 只测类默认）
"""
from app.config import Settings


def _defaults() -> Settings:
    return Settings(
        _env_file=None,
        SECRET_KEY="x", GLM_API_KEY="x", JWT_SECRET_KEY="x",
    )


def test_ocr_defaults():
    s = _defaults()
    assert s.OCR_PROVIDER == "hybrid"
    assert s.VLM_MODEL_NAME == "glm-4.1v-flash"
    assert s.OCR_MIN_CONFIDENCE == 0.85


def test_allowed_extensions_default():
    s = _defaults()
    assert ".doc" not in s.ALLOWED_EXTENSIONS  # 老二进制格式移除
    for ext in (".pdf", ".jpg", ".jpeg", ".png", ".docx"):
        assert ext in s.ALLOWED_EXTENSIONS
