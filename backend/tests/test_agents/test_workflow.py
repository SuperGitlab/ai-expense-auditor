"""
LangGraph审核工作流测试（真实调用Kimi，默认跳过）

启用方式（需配置LLM_API_KEY且测试库可达）:
    uv run pytest -m llm -v
"""
import pytest

from tests.conftest import register_and_login, requires_db

pytestmark = [pytest.mark.llm, requires_db]

EXPENSE_PAYLOAD = {
    "title": "出差报销-上海",
    "expense_type": "travel",
    "description": "上海客户拜访",
    "items": [
        {
            "category_id": 1,
            "description": "高铁票",
            "amount": "150.00",
            "expense_date": "2026-08-28",
            "invoice_no": "INV99998888",
        }
    ],
}


def test_full_review_workflow(client, db_session):
    """完整AI审核：低风险小额有发票单应被自动通过或转人工"""
    headers = register_and_login(client, "wf_user")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    expense_id = resp.json()["id"]

    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    assert resp.status_code == 200

    # 手动触发AI审核
    resp = client.post("/api/agent/review", json={"expense_id": expense_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["risk_level"] in ("low", "medium", "high")
    assert 0 <= float(body["risk_score"]) <= 100
    assert body["decision"] in ("auto_approve", "manual_review", "auto_reject")
    assert body["elapsed_seconds"] > 0

    # 低风险场景下决策应为自动通过（GLM评估正常时）
    if body["risk_level"] == "low" and not body["workflow_errors"]:
        assert body["decision"] == "auto_approve"
