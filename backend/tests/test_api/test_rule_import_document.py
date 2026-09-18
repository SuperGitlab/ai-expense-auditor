"""
制度文档导入接口测试（需测试DB）
抽取端点（解析/LLM均打桩）+ 确认端点（Rule入库 + 向量库 append/replace两模式）
"""
from app.services.rule_import_service import ExtractedRule, ExtractedRules

from tests.conftest import register_and_login, requires_db

EXTRACT_URL = "/api/rules/import/document/extract"
CONFIRM_URL = "/api/rules/import/document/confirm"

FAKE_TEXT = "第一章 住宿标准\n一线城市每晚上限600元。\n第二章 餐饮标准\n单次餐饮上限200元。"


def _admin(client, name="rdoc_admin"):
    return register_and_login(client, name, role="admin")


def _fake_drafts():
    """1条好草稿 + 1条坏草稿（类别不存在→issues标注）"""
    return ExtractedRules(
        rules=[
            ExtractedRule(name="住宿上限", code="DOC_NEW_1", field_name="amount",
                          operator="gt", threshold="600", quote="每晚上限600元"),
            ExtractedRule(name="坏行", code="DOC_BAD_1", category_code="ghost",
                          field_name="amount", operator="gt", threshold="1", quote="原文"),
        ]
    )


class FakeKB:
    """记录import调用的假知识库（端点只调import_policy_document）"""

    def __init__(self):
        self.calls = []

    def import_policy_document(self, sections, source, replace=False):
        self.calls.append({"source": source, "replace": replace, "sections": len(sections)})
        return (len(sections), replace)


def _rule(code, **over):
    base = {
        "name": "文档导入规则",
        "code": code,
        "rule_type": "amount_limit",
        "field_name": "amount",
        "operator": "gt",
        "threshold": "500",
        "severity": "warn",
        "risk_points": 10,
    }
    base.update(over)
    return base


def _sections():
    return [{"title": "第一章 住宿标准", "content": "一线城市每晚上限600元。"}]


# ---------- 抽取端点 ----------

@requires_db
def test_extract_requires_admin(client):
    """非admin 403"""
    headers = register_and_login(client, "rdoc_emp")
    resp = client.post(
        EXTRACT_URL, files={"file": ("t.docx", b"x", "application/octet-stream")}, headers=headers
    )
    assert resp.status_code == 403


@requires_db
def test_extract_rejects_txt(client):
    """仅支持docx/pdf：.txt 400"""
    headers = _admin(client, "rdoc_txt")
    resp = client.post(
        EXTRACT_URL, files={"file": ("notes.txt", "文本内容".encode(), "text/plain")}, headers=headers
    )
    assert resp.status_code == 400
    assert "docx" in resp.json()["detail"]


@requires_db
def test_extract_flow(client, monkeypatch):
    """抽取正常流：章节切分正确、坏行标issues、不入库不碰知识库"""
    import app.services.rule_import_service as svc
    from app.api.endpoints import rule_import as rim

    monkeypatch.setattr(svc, "read_document_text", lambda path: (FAKE_TEXT, "docx"))
    monkeypatch.setattr(svc, "extract_rules_from_text", lambda text, codes: _fake_drafts())
    fake_kb = FakeKB()
    monkeypatch.setattr(rim, "knowledge_base", fake_kb)

    headers = _admin(client, "rdoc_flow")
    resp = client.post(
        EXTRACT_URL, files={"file": ("制度.docx", b"fake", "application/octet-stream")}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "制度.docx"
    assert [s["title"] for s in body["sections"]] == ["第一章 住宿标准", "第二章 餐饮标准"]
    assert body["stats"]["method"] == "docx"
    assert body["rules"][0]["issues"] == []
    assert body["rules"][0]["quote"] == "每晚上限600元"
    assert body["rules"][1]["issues"]  # ghost类别被标注

    # 未入库：规则列表无新code、知识库零调用
    codes = {r["code"] for r in client.get("/api/rules", headers=headers).json()}
    assert not (codes & {"DOC_NEW_1", "DOC_BAD_1"})
    assert fake_kb.calls == []


@requires_db
def test_extract_text_too_short_422(client, monkeypatch):
    """解析文本过短（扫描件失败）：422"""
    import app.services.rule_import_service as svc

    monkeypatch.setattr(svc, "read_document_text", lambda path: ("太短", "pdf_ocr"))
    headers = _admin(client, "rdoc_short")
    resp = client.post(
        EXTRACT_URL, files={"file": ("s.pdf", b"fake", "application/pdf")}, headers=headers
    )
    assert resp.status_code == 422


@requires_db
def test_extract_llm_failure_502(client, monkeypatch):
    """LLM抽取失败：502请重试"""
    import app.services.rule_import_service as svc

    def _boom(text, codes):
        raise svc.LLMExtractionError("upstream down")

    monkeypatch.setattr(svc, "read_document_text", lambda path: (FAKE_TEXT, "docx"))
    monkeypatch.setattr(svc, "extract_rules_from_text", _boom)
    headers = _admin(client, "rdoc_llm502")
    resp = client.post(
        EXTRACT_URL, files={"file": ("a.docx", b"fake", "application/octet-stream")}, headers=headers
    )
    assert resp.status_code == 502


# ---------- 确认端点 ----------

@requires_db
def test_confirm_append(client, monkeypatch):
    """追加模式：规则入库+知识库写入（replace=False）"""
    from app.api.endpoints import rule_import as rim

    fake_kb = FakeKB()
    monkeypatch.setattr(rim, "knowledge_base", fake_kb)
    headers = _admin(client, "rdoc_append")
    resp = client.post(
        CONFIRM_URL,
        json={
            "source": "新版制度.docx",
            "mode": "append",
            "rules": [_rule("DOC_A_1"), _rule("DOC_A_2")],
            "sections": _sections(),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["cleared_policies"] is False

    assert len(fake_kb.calls) == 1
    call = fake_kb.calls[0]
    assert call["source"] == "新版制度.docx"
    assert call["replace"] is False
    assert call["sections"] == 1

    codes = {r["code"] for r in client.get("/api/rules", headers=headers).json()}
    assert {"DOC_A_1", "DOC_A_2"} <= codes


@requires_db
def test_confirm_replace(client, monkeypatch):
    """替换模式：知识库收到replace=True"""
    from app.api.endpoints import rule_import as rim

    fake_kb = FakeKB()
    monkeypatch.setattr(rim, "knowledge_base", fake_kb)
    headers = _admin(client, "rdoc_replace")
    resp = client.post(
        CONFIRM_URL,
        json={
            "source": "替换制度.docx",
            "mode": "replace",
            "rules": [_rule("DOC_R_1")],
            "sections": _sections(),
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["cleared_policies"] is True
    assert fake_kb.calls[0]["replace"] is True


@requires_db
def test_confirm_invalid_row_no_knowledge_base(client, monkeypatch):
    """确认含坏行：400全拒，知识库零调用、DB零写入"""
    from app.api.endpoints import rule_import as rim

    fake_kb = FakeKB()
    monkeypatch.setattr(rim, "knowledge_base", fake_kb)
    headers = _admin(client, "rdoc_badrow")
    resp = client.post(
        CONFIRM_URL,
        json={
            "source": "坏行.docx",
            "mode": "append",
            "rules": [_rule("DOC_GOOD"), _rule("DOC_BAD", risk_points=999)],
            "sections": _sections(),
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["index"] == 1
    assert fake_kb.calls == []
    codes = {r["code"] for r in client.get("/api/rules", headers=headers).json()}
    assert "DOC_GOOD" not in codes


@requires_db
def test_confirm_empty_sections_422(client):
    """sections为空：422（防清空后无写入）"""
    headers = _admin(client, "rdoc_nosec")
    resp = client.post(
        CONFIRM_URL,
        json={"source": "x", "mode": "replace", "rules": [], "sections": []},
        headers=headers,
    )
    assert resp.status_code == 422


@requires_db
def test_confirm_doc_only_without_rules(client, monkeypatch):
    """rules为空=仅导入原文入知识库：200 imported=0"""
    from app.api.endpoints import rule_import as rim

    fake_kb = FakeKB()
    monkeypatch.setattr(rim, "knowledge_base", fake_kb)
    headers = _admin(client, "rdoc_donly")
    resp = client.post(
        CONFIRM_URL,
        json={"source": "纯制度.docx", "mode": "append", "rules": [], "sections": _sections()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 0
    assert len(fake_kb.calls) == 1
