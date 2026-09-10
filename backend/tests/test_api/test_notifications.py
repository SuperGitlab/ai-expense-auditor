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
