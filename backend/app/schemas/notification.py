"""
通知数据模式
站内通知的响应结构
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    """通知响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    content: Optional[str] = None
    type: str
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    """通知列表响应（paginate结构 + 未读数）"""
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    unread_count: int
