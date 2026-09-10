"""
报表接口测试
summary/trends/by-category + xlsx导出 + 权限
"""
from tests.conftest import register_and_login, requires_db


@requires_db
def test_summary_requires_role(client):
    resp = client.get("/api/reports/summary", headers=register_and_login(client, "rp_e1"))
    assert resp.status_code == 403


@requires_db
def test_summary_and_trends(client):
    headers = register_and_login(client, "rp_f1", role="finance")
    resp = client.get("/api/reports/summary", headers=headers)
    assert resp.status_code == 200
    assert "total" in resp.json()

    resp = client.get("/api/reports/trends?months=6", headers=headers)
    assert resp.status_code == 200
    assert "months" in resp.json()


@requires_db
def test_export_denied_for_employee(client):
    resp = client.get("/api/reports/export", headers=register_and_login(client, "rp_e2"))
    assert resp.status_code == 403


@requires_db
def test_export_returns_xlsx(client):
    """导出200、xlsx媒体类型、PK(zip)魔数、attachment头"""
    headers = register_and_login(client, "rp_f2", role="finance")
    resp = client.get("/api/reports/export?months=6", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert resp.content[:2] == b"PK"
    assert "attachment" in resp.headers["content-disposition"]
