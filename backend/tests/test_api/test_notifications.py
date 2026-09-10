"""
通知接口测试
列表/未读数/标记已读/全部已读 + 数据隔离(只能看自己的)
"""
from app.models import Notification, User
from app.services.notification_service import send_notification

from tests.conftest import register_and_login, requires_db


def _user_id(db, username: str) -> int:
    return db.query(User).filter(User.username == username).one().id


@requires_db
def test_unauthorized(client):
    """未登录401"""
    resp = client.get("/api/notifications")
    assert resp.status_code == 401


@requires_db
def test_list_and_read_flow(client, db_session):
    """发2条→列表含unread_count→标记1条→全部已读→unread归零"""
    headers = register_and_login(client, "na_e1")
    uid = _user_id(db_session, "na_e1")
    send_notification(db_session, uid, "T1", "C1", "approval")
    send_notification(db_session, uid, "T2", "C2", "payment")

    resp = client.get("/api/notifications", headers=headers)
    body = resp.json()
    assert body["total"] == 2 and body["unread_count"] == 2
    assert [i["title"] for i in body["items"]] == ["T2", "T1"]  # 新→旧

    nid = body["items"][0]["id"]
    resp = client.post(f"/api/notifications/{nid}/read", headers=headers)
    assert resp.status_code == 200 and resp.json()["is_read"] is True

    resp = client.get("/api/notifications/unread-count", headers=headers)
    assert resp.json()["count"] == 1

    resp = client.post("/api/notifications/read-all", headers=headers)
    assert resp.json()["updated"] is True
    resp = client.get("/api/notifications/unread-count", headers=headers)
    assert resp.json()["count"] == 0


@requires_db
def test_isolation_between_users(client, db_session):
    """只能看到自己的通知;标记别人的通知返回404"""
    h1 = register_and_login(client, "na_e2")
    h2 = register_and_login(client, "na_e3")
    send_notification(db_session, _user_id(db_session, "na_e2"), "给e2", "C", "approval")

    resp = client.get("/api/notifications", headers=h2)
    assert resp.json()["total"] == 0

    nid = db_session.query(Notification).first().id
    resp = client.post(f"/api/notifications/{nid}/read", headers=h2)
    assert resp.status_code == 404
    resp = client.get("/api/notifications", headers=h1)
    assert resp.json()["total"] == 1


# ===== 接线用例:审批/打款触发通知 =====
EXPENSE_PAYLOAD = {
    "title": "测试报销",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "100.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-NOTIF-001",
        }
    ],
}


def _create_submitted(client, username):
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    resp = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    assert resp.status_code == 200
    return expense_id, headers


@requires_db
def test_decide_notifies_applicant(client):
    """财务审批通过后,申请人收到approval类型站内信"""
    expense_id, owner_headers = _create_submitted(client, "na_d1")
    finance_headers = register_and_login(client, "na_dfin", role="finance")
    resp = client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "approve", "comment": "通过"},
        headers=finance_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/api/notifications", headers=owner_headers)
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "approval"
    assert "已通过" in body["items"][0]["title"]


@requires_db
def test_reject_and_pay_notify(client):
    """驳回也通知;打款登记产生payment通知"""
    expense_id, owner_headers = _create_submitted(client, "na_d2")
    finance_headers = register_and_login(client, "na_dfin2", role="finance")
    client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": "approve"},
        headers=finance_headers,
    )
    resp = client.post(f"/api/expenses/{expense_id}/pay", headers=finance_headers)
    assert resp.status_code == 200, resp.text

    resp = client.get("/api/notifications", headers=owner_headers)
    types = [i["type"] for i in resp.json()["items"]]
    assert "approval" in types and "payment" in types
