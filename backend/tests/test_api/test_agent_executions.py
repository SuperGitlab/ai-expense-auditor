"""
节点执行轨迹接口测试：画布数据源
5节点全量返回（未启动补pending）、label中文、权限同报销单读取
"""
from app.agents import workflow as wf
from app.models import AgentNodeRun

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "轨迹接口测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-EXEC-001",
        }
   ],
}


def _submitted_expense(client, username: str) -> tuple[int, dict]:
    """建单并提交（=AI执行中），返回(单据id, 申请人headers)"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    assert client.post(f"/api/expenses/{expense_id}/submit", headers=headers).status_code == 200
    return expense_id, headers


@requires_db
def test_executions_returns_all_nodes_with_labels(client, db_session):
    """返回5节点全量：有轨迹行的带状态，缺行补pending；label中文；带单据状态"""
    expense_id, headers = _submitted_expense(client, "exec_e1")

    # 手写两条轨迹：一条进行中、一条完成（模拟埋点）
    wf._record_node(db_session, expense_id, "document", "succeeded", detail="解析完成，异常0项")
    wf._record_node(db_session, expense_id, "rule", "running")

    resp = client.get(f"/api/agent/executions/{expense_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["expense_status"] == "submitted"
    assert [n["node"] for n in body["nodes"]] == ["document", "rule", "rag", "risk", "decision"]
    assert [n["label"] for n in body["nodes"]] == ["单据解析", "规则校验", "RAG检索", "风险评估", "终审裁决"]

    by_node = {n["node"]: n for n in body["nodes"]}
    assert by_node["document"]["status"] == "succeeded"
    assert "异常0项" in by_node["document"]["detail"]
    assert by_node["document"]["started_at"] is not None
    assert by_node["rule"]["status"] == "running"
    assert by_node["rule"]["finished_at"] is None
    # 未启动的节点补pending、无时间戳
    assert by_node["rag"]["status"] == "pending"
    assert by_node["rag"]["started_at"] is None and by_node["rag"]["detail"] is None


@requires_db
def test_executions_shows_overridden_decision(client, db_session):
    """人审接管后的overridden轨迹原样透出（画布紫标「人审结果优先」数据源）"""
    expense_id, headers = _submitted_expense(client, "exec_e2")
    wf._record_node(db_session, expense_id, "decision", "overridden",
                    detail="人审结果优先：人工已将单据流转为 rejected")

    resp = client.get(f"/api/agent/executions/{expense_id}", headers=headers)
    assert resp.status_code == 200
    by_node = {n["node"]: n for n in resp.json()["nodes"]}
    assert by_node["decision"]["status"] == "overridden"
    assert "人审结果优先" in by_node["decision"]["detail"]


@requires_db
def test_executions_permission(client):
    """无关employee不可看（403）；admin可看任意单"""
    expense_id, _ = _submitted_expense(client, "exec_e3")

    stranger = register_and_login(client, "exec_stranger")
    resp = client.get(f"/api/agent/executions/{expense_id}", headers=stranger)
    assert resp.status_code == 403

    admin = register_and_login(client, "exec_admin1", role="admin")
    resp = client.get(f"/api/agent/executions/{expense_id}", headers=admin)
    assert resp.status_code == 200


@requires_db
def test_executions_missing_expense(client):
    """不存在的报销单→404"""
    headers = register_and_login(client, "exec_e4")
    resp = client.get("/api/agent/executions/999999", headers=headers)
    assert resp.status_code == 404
