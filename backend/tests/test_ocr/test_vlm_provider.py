"""
GLM-VLM抽取测试
JSON解析(纯/markdown fence/垃圾)；LLM调用mock；失败返回None
"""
from app.ocr import vlm_provider


def test_parse_plain_json():
    assert vlm_provider._parse_json('{"invoice_no": "123"}') == {"invoice_no": "123"}


def test_parse_fenced_json():
    s = '```json\n{"invoice_no": "123", "date": "2026-08-15"}\n```'
    assert vlm_provider._parse_json(s) == {"invoice_no": "123", "date": "2026-08-15"}


def test_parse_garbage_returns_none():
    assert vlm_provider._parse_json("抱歉我无法识别") is None
    assert vlm_provider._parse_json('["not", "dict"]') is None


def test_extract_fields_llm_error(monkeypatch, tmp_path):
    """LLM抛异常 → None（pipeline降级），不外抛"""
    import langchain_openai

    class _Boom:
        def __init__(self, **kw):
            raise RuntimeError("api down")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Boom)
    p = tmp_path / "inv.png"
    p.write_bytes(b"\x89PNG fake")
    assert vlm_provider.extract_fields(p) is None


def test_extract_fields_success(monkeypatch, tmp_path):
    class _Resp:
        content = '{"invoice_no": "25617000000123456789", "amount_total": "100.00"}'

    class _FakeLLM:
        def __init__(self, **kw):
            pass
        def invoke(self, messages):
            assert messages[0].content[0]["type"] == "text"
            assert messages[0].content[1]["type"] == "image_url"
            return _Resp()

    import langchain_openai
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _FakeLLM)
    p = tmp_path / "inv.jpg"
    p.write_bytes(b"\xff\xd8 fake jpeg")
    fields = vlm_provider.extract_fields(p)
    assert fields == {"invoice_no": "25617000000123456789", "amount_total": "100.00"}
