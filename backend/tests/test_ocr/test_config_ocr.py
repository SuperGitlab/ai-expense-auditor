"""
OCR相关配置默认值测试
不依赖DB/env（_env_file=None 只测类默认）
"""
import pytest

from app.config import Settings

# 与Settings字段同名的环境变量键（VLM_MODEL_NAME等）——pymilvus在import时会
# 调load_dotenv()把根.env灌进os.environ，环境变量源优先级高于类默认值，
# _env_file=None拦不住；测试期间删掉这些键才能真·只测类默认
FIELD_ENV_KEYS = [k.upper() for k in Settings.model_fields]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """屏蔽os.environ里与Settings字段同名的键（测试结束后monkeypatch自动还原）"""
    for key in FIELD_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


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
