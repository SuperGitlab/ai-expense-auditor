"""
制度文档导入接口测试（需测试DB）
抽取已异步化（提交即回task_id + 轮询status取草稿；解析/LLM均打桩）+ 确认端点（Rule入库 + 向量库 append/replace两模式）
"""
import pytest

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


# ---------- 抽取（异步：提交即回 + 轮询状态） ----------

def test_extraction_task_registered():
    """worker必须include抽取任务模块：不include则消息按unregistered丢弃（review任务踩过的坑）"""
    from app.tasks import celery_app

    assert "app.tasks.rule_extraction" in (celery_app.conf.include or ())


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


def _draft_dict():
    """任务SUCCESS时存Redis、轮询返回的草稿结构"""
    return {
        "filename": "制度.docx",
        "source": "制度.docx",
        "sections": [
            {"title": "第一章 住宿标准", "content": "一线城市每晚上限600元。"},
            {"title": "第二章 餐饮标准", "content": "单次餐饮上限200元。"},
        ],
        "rules": [
            {
                "name": "住宿上限", "code": "DOC_NEW_1", "rule_type": "custom",
                "category_code": None, "field_name": "amount", "operator": "gt",
                "threshold": "600", "severity": "warn", "risk_points": 10,
                "quote": "每晚上限600元", "issues": [],
            },
        ],
        "stats": {"text_chars": 40, "method": "docx", "sections": 2, "rules": 1},
    }


@requires_db
def test_extract_submits_and_polls(client, monkeypatch):
    """提交即回task_id（不阻塞等LLM）；文件落盘传给任务；轮询端点SUCCESS带草稿/FAILURE带错误"""
    from pathlib import Path

    from app.api.endpoints import rule_import as rim

    dispatched = {}

    class FakeTask:
        id = "task-123"

        @staticmethod
        def delay(path, filename, user_id):
            dispatched.update(path=path, filename=filename, user_id=user_id)
            return FakeTask

    monkeypatch.setattr(rim, "extract_document_task", FakeTask)

    states = {"task-123": ("PENDING", None)}

    class FakeCelery:
        @staticmethod
        def AsyncResult(tid):
            state, result = states[tid]
            return type("R", (), {"state": state, "result": result})()

    monkeypatch.setattr(rim, "celery_app", FakeCelery)

    headers = _admin(client, "rdoc_async")
    resp = client.post(
        EXTRACT_URL, files={"file": ("制度.docx", b"fake", "application/octet-stream")}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"task_id": "task-123", "filename": "制度.docx"}
    assert dispatched["filename"] == "制度.docx"
    assert dispatched["user_id"] > 0
    assert Path(dispatched["path"]).exists()  # 文件已落盘等worker取
    Path(dispatched["path"]).unlink(missing_ok=True)  # 测试里没worker，手动清理

    # 提交阶段不入库
    codes = {r["code"] for r in client.get("/api/rules", headers=headers).json()}
    assert "DOC_NEW_1" not in codes

    # PENDING：只有state
    resp = client.get(f"{EXTRACT_URL}/task-123", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "PENDING" and body["draft"] is None

    # SUCCESS：带完整草稿
    states["task-123"] = ("SUCCESS", _draft_dict())
    resp = client.get(f"{EXTRACT_URL}/task-123", headers=headers)
    body = resp.json()
    assert body["state"] == "SUCCESS"
    assert [s["title"] for s in body["draft"]["sections"]] == ["第一章 住宿标准", "第二章 餐饮标准"]
    assert body["draft"]["rules"][0]["quote"] == "每晚上限600元"

    # FAILURE：带错误信息
    states["task-123"] = ("FAILURE", ValueError("规则抽取失败，请重试: upstream down"))
    resp = client.get(f"{EXTRACT_URL}/task-123", headers=headers)
    body = resp.json()
    assert body["state"] == "FAILURE"
    assert "upstream down" in body["error"]


@requires_db
def test_extraction_task_flow(client, db_session, monkeypatch, tmp_path):
    """后台任务编排：解析→抽取→切分→标注（svc打桩）、临时文件用后即删、不入库"""
    import app.services.rule_import_service as svc
    from app.tasks.rule_extraction import run_document_extraction

    monkeypatch.setattr(svc, "read_document_text", lambda path: (FAKE_TEXT, "docx"))
    monkeypatch.setattr(svc, "extract_rules_from_text", lambda text, codes: _fake_drafts())

    p = tmp_path / "t.docx"
    p.write_bytes(b"fake")
    draft = run_document_extraction(db_session, str(p), "制度.docx")

    assert not p.exists()  # 任务结束删除临时文件
    assert [s["title"] for s in draft["sections"]] == ["第一章 住宿标准", "第二章 餐饮标准"]
    assert draft["stats"]["method"] == "docx"
    assert draft["rules"][0]["quote"] == "每晚上限600元"
    assert draft["rules"][0]["issues"] == []
    assert draft["rules"][1]["issues"]  # ghost类别被标注

    headers = _admin(client, "rdoc_taskflow")
    codes = {r["code"] for r in client.get("/api/rules", headers=headers).json()}
    assert not (codes & {"DOC_NEW_1", "DOC_BAD_1"})  # 草稿不写Rule表


@requires_db
def test_extraction_task_failure_notifies(client, monkeypatch, tmp_path):
    """任务失败：临时文件清理 + 发失败站内信 + 异常上抛（Celery记FAILURE）"""
    import app.services.notification_service as notif
    import app.services.rule_import_service as svc
    from app.tasks.rule_extraction import extract_document_task

    monkeypatch.setattr(svc, "read_document_text", lambda path: (FAKE_TEXT, "docx"))

    def _boom(text, codes):
        raise svc.LLMExtractionError("upstream down")

    monkeypatch.setattr(svc, "extract_rules_from_text", _boom)
    sent = []
    monkeypatch.setattr(
        notif, "send_notification",
        lambda db, uid, title, content, ntype: sent.append((uid, title, content)) or True,
    )

    _admin(client, "rdoc_taskfail")  # 建admin拿user_id（表结构已就绪）
    p = tmp_path / "f.docx"
    p.write_bytes(b"x")
    with pytest.raises(Exception, match="upstream down"):
        extract_document_task(str(p), "失败.docx", 1)

    assert not p.exists()
    assert sent and "解析失败" in sent[0][1] and "失败.docx" in sent[0][2]


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
