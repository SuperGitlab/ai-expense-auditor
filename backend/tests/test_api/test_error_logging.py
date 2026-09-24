"""
错误日志可见性测试：4xx拒绝原因必须落服务端日志（不能只进HTTP响应体）
覆盖：规则导入逐行拒绝明细（rule_import）+ 全局HTTPException/422处理器（main）
"""
import logging

from tests.conftest import register_and_login, requires_db

CONFIRM_URL = "/api/rules/import/document/confirm"


def _rule(code, **over):
    base = {
        "name": "日志测试规则", "code": code, "rule_type": "amount_limit",
        "field_name": "amount", "operator": "gt", "threshold": "500",
        "severity": "warn", "risk_points": 10,
    }
    base.update(over)
    return base


@requires_db
def test_row_rejection_logged(client, caplog):
    """文档确认逐行校验被拒：控制台必须看到具体行与原因（不再只有一行400访问日志）"""
    headers = register_and_login(client, "rlog_admin", role="admin")
    with caplog.at_level(logging.WARNING, logger="app.api.endpoints.rule_import"):
        resp = client.post(
            CONFIRM_URL,
            json={
                "source": "日志.docx",
                "mode": "append",
                "rules": [_rule("RLOG_BAD", risk_points=999)],
                "sections": [{"title": "第一章", "content": "内容"}],
            },
            headers=headers,
        )
    assert resp.status_code == 400
    recs = [r.getMessage() for r in caplog.records if "规则导入整体拒绝" in r.getMessage()]
    assert recs and "RLOG_BAD" in recs[0] and "文档确认" in recs[0]


@requires_db
def test_http_exception_logged(client, caplog):
    """未登录401：全局处理器落日志（detail默认只回前端响应体，控制台看不到）"""
    with caplog.at_level(logging.WARNING, logger="app.main"):
        resp = client.get("/api/rules")
    assert resp.status_code == 401
    assert any("/api/rules" in r.getMessage() for r in caplog.records)


@requires_db
def test_request_validation_422_logged(client, caplog):
    """请求体schema校验失败：422处理器落日志（errors含字段路径与原因）"""
    headers = register_and_login(client, "rlog_admin2", role="admin")
    with caplog.at_level(logging.WARNING, logger="app.main"):
        resp = client.post(
            CONFIRM_URL,
            json={"source": "x", "mode": "replace", "rules": [], "sections": []},
            headers=headers,
        )
    assert resp.status_code == 422
    assert any("参数校验失败" in r.getMessage() for r in caplog.records)
