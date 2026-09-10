"""
站内通知接口
我的通知列表、未读数、标记已读
"""
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DBSession
from app.models import Notification
from app.schemas.notification import NotificationListResponse, NotificationResponse
from app.utils.helpers import paginate

router = APIRouter(prefix="/api/notifications", tags=["站内通知"])


def _unread_count(db, user_id: int) -> int:
    return db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False,  # noqa: E712
    ).count()


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    db: DBSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    """我的通知列表(新→旧,含未读数)"""
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    total = query.count()
    items = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    data = paginate(items, total, page, page_size)
    data["unread_count"] = _unread_count(db, current_user.id)
    return data


@router.get("/unread-count")
def unread_count(db: DBSession, current_user: CurrentUser):
    """未读通知数"""
    return {"count": _unread_count(db, current_user.id)}


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(notification_id: int, db: DBSession, current_user: CurrentUser):
    """标记单条已读(只能操作自己的)"""
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="通知不存在")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


@router.post("/read-all")
def mark_all_read(db: DBSession, current_user: CurrentUser):
    """全部标记已读"""
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,  # noqa: E712
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"updated": True}
