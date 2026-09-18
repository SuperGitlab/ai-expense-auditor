"""
JSON直导接口测试（需测试DB）
语义：全量校验有错全拒（400逐行明细）、合法批量入库、不碰向量库
"""
from tests.conftest import register_and_login, requires_db

URL = "/api/rules/import/json"


def _rule(code, **over):
    base = {
        "name": "导入测试规则",
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


def _admin(client, name="rim_admin"):
    return register_and_login(client, name, role="admin")


@requires_db
def test_import_json_requires_auth(client):
    """未登录401"""
    resp = client.post(URL, json={"rules": [_rule("A_1")]})
    assert resp.status_code == 401


@requires_db
def test_import_json_requires_admin(client):
    """非admin 403"""
    headers = register_and_login(client, "rim_emp")
    resp = client.post(URL, json={"rules": [_rule("A_1")]}, headers=headers)
    assert resp.status_code == 403


@requires_db
def test_import_json_happy_path(client, db_session):
    """合法批量导入：category_code解析成category_id"""
    from app.models import Category

    headers = _admin(client, "rim_happy")
    resp = client.post(
        URL,
        json={"rules": [_rule("IMP_1"), _rule("IMP_2", category_code="meal")]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["vector_written"] == 0
    codes = {r["code"] for r in body["rules"]}
    assert codes == {"IMP_1", "IMP_2"}

    # meal类别id解析正确（conftest种了travel/meal两个类别）
    meal_id = db_session.query(Category).filter(Category.code == "meal").one().id
    meal_rule = next(r for r in body["rules"] if r["code"] == "IMP_2")
    assert meal_rule["category_id"] == meal_id


@requires_db
def test_import_json_code_conflict_400(client):
    """code与库中重复：400逐行明细，库条数不变"""
    headers = _admin(client, "rim_conflict")
    # 先经现有CRUD接口建一条
    client.post("/api/rules", json=_rule("IMP_DUP"), headers=headers)

    before = len(client.get("/api/rules", headers=headers).json())
    resp = client.post(URL, json={"rules": [_rule("IMP_DUP"), _rule("IMP_OK_1")]}, headers=headers)
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["index"] == 0
    assert "IMP_DUP" in body["errors"][0]["errors"][0]
    after = len(client.get("/api/rules", headers=headers).json())
    assert after == before  # 全拒：好行也没写入


@requires_db
def test_import_json_bad_row_nothing_written(client):
    """1好1坏（risk_points越界）：400，好行也未写入"""
    headers = _admin(client, "rim_badrow")
    resp = client.post(
        URL,
        json={"rules": [_rule("IMP_GOOD"), _rule("IMP_BAD", risk_points=999)]},
        headers=headers,
    )
    assert resp.status_code == 400
    errors = resp.json()["errors"]
    assert len(errors) == 1 and errors[0]["index"] == 1

    codes = {r["code"] for r in client.get("/api/rules", headers=headers).json()}
    assert "IMP_GOOD" not in codes


@requires_db
def test_import_json_batch_internal_duplicate(client):
    """批内code重复：400"""
    headers = _admin(client, "rim_dup2")
    resp = client.post(
        URL, json={"rules": [_rule("IMP_SAME"), _rule("IMP_SAME")]}, headers=headers
    )
    assert resp.status_code == 400
    # errors只含失败行：两行同code时第0行合法、第1行报"重复"
    errs = resp.json()["errors"]
    assert len(errs) == 1 and errs[0]["index"] == 1
    assert any("重复" in e for e in errs[0]["errors"])


@requires_db
def test_import_json_empty_rejected(client):
    """空rules：422（Pydantic min_length）"""
    headers = _admin(client, "rim_empty")
    resp = client.post(URL, json={"rules": []}, headers=headers)
    assert resp.status_code == 422


@requires_db
def test_import_json_never_touches_knowledge_base(client, monkeypatch):
    """JSON通道不碰知识库"""
    from app.api.endpoints import rule_import as rim

    calls = []

    class Recorder:
        def import_policy_document(self, *a, **kw):
            calls.append((a, kw))
            return (0, False)

        def clear_policies(self):
            calls.append("clear")
            return True

    monkeypatch.setattr(rim, "knowledge_base", Recorder())
    headers = _admin(client, "rim_nochroma")
    resp = client.post(URL, json={"rules": [_rule("IMP_NC")]}, headers=headers)
    assert resp.status_code == 200
    assert calls == []
