# 阶段① 实施计划:通知接线 + 报表导出 + 用户管理页面

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地规格 [2026-09-09-unfinished-features-design.md](../specs/2026-09-09-unfinished-features-design.md) 的阶段①——站内信+邮件通知(3 个触发点)、报表 xlsx 导出、admin 用户管理页面(含后端自我保护)。

**Architecture:** 后端沿用「endpoint → service → model」分层与 conftest 的 DB-skip 测试模式;通知走 `notification_service`(站内信落库必有 + `notification_tool.notify` 邮件尽力而为)。前端沿用 `api/*.ts + views/*.vue` 模式,铃铛挂在 MainLayout 顶栏,30s 轮询未读数。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · openpyxl(新依赖) · Vue3 · Element Plus

**重要约束:**
- 依赖安装由**用户**执行(本计划只列命令,不代跑):`uv add openpyxl`
- 测试命令在**项目根目录**执行:`uv run pytest ...`(conftest 自动处理 sys.path);无测试 DB 时 DB 用例自动跳过属正常
- 前端无测试框架,验证方式为 `cd frontend && npm run build`(含 vue-tsc 类型检查)

---

## 文件结构

| 动作 | 文件 | 职责 |
|---|---|---|
| Create | `backend/app/models/notification.py` | notifications 表模型 |
| Modify | `backend/app/models/__init__.py` | 导出新模型 |
| Create | `backend/app/schemas/notification.py` | 通知响应模式 |
| Create | `backend/app/services/notification_service.py` | 发送核心 + 3 个事件辅助 |
| Create | `backend/app/api/endpoints/notifications.py` | 通知 4 个接口 |
| Modify | `backend/app/main.py` | 注册路由 |
| Modify | `backend/app/services/approval_service.py` | decide 后通知 |
| Modify | `backend/app/services/expense_service.py` | pay 后通知 |
| Modify | `backend/app/agents/workflow.py` | AI 审核后通知 |
| Modify | `backend/app/services/report_service.py` | export_report |
| Modify | `backend/app/api/endpoints/reports.py` | /export 端点 |
| Modify | `backend/app/api/endpoints/users.py` | 自我保护校验 |
| Create | `frontend/src/api/notification.ts` / `api/user.ts` | 新 API 模块 |
| Modify | `frontend/src/types/index.ts` | 通知类型 |
| Modify | `frontend/src/layout/MainLayout.vue` | 铃铛 + 菜单项 |
| Modify | `frontend/src/views/ReportsView.vue` + `api/report.ts` | 导出按钮 |
| Create | `frontend/src/views/UserManagementView.vue` | 用户管理页 |
| Modify | `frontend/src/router/index.ts` | /users 路由 |
| Modify | `README.md` / `README.zh-CN.md` | 更新 Work in Progress 三行 |
| Test | `backend/tests/test_services/test_notification_service.py`、`test_api/test_notifications.py`、`test_api/test_reports.py`、`test_api/test_users.py`、`test_agents/test_workflow_notify.py` | 本阶段全部用例 |

---

### Task 0: 前置准备

- [ ] **Step 1: 创建功能分支**

```bash
git checkout -b feat/phase1-notify-export-users
```

- [ ] **Step 2: 用户安装依赖**(提示用户执行,确认完成后再继续)

```bash
uv add openpyxl
```

---

### Task 1: Notification 模型 + 通知服务

**Files:**
- Create: `backend/app/models/notification.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/schemas/notification.py`
- Create: `backend/app/services/notification_service.py`
- Test: `backend/tests/test_services/test_notification_service.py`

- [ ] **Step 1: 写失败测试**

```python
"""
通知服务测试
核心契约:站内信落库必有 + 邮件尽力而为(失败不影响主流程)
"""
import pytest

from app.models import Notification, User
from app.services import notification_service
from app.services.notification_service import (notify_ai_review,
                                               notify_human_decision,
                                               notify_payment,
                                               send_notification)

from tests.conftest import requires_db


def _create_user(db, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@test.com",
        hashed_password="x",
        department="测试部",
    )
    db.add(user)
    db.commit()
    return user


def _create_expense(db, user: User, expense_no: str = "EXP-TEST-0001"):
    from app.models import Expense, ExpenseStatus
    expense = Expense(
        expense_no=expense_no,
        title="测试报销单",
        user_id=user.id,
        total_amount=100,
        status=ExpenseStatus.SUBMITTED,
    )
    db.add(expense)
    db.commit()
    return expense


@requires_db
def test_send_notification_creates_row(db_session):
    """站内信必须落库:标题/内容/类型/未读,返回True"""
    user = _create_user(db_session, "ns_u1")
    ok = send_notification(db_session, user.id, "标题A", "内容B", "approval")
    assert ok is True
    row = db_session.query(Notification).filter(Notification.user_id == user.id).one()
    assert row.title == "标题A"
    assert row.content == "内容B"
    assert row.type == "approval"
    assert row.is_read is False


@requires_db
def test_email_is_best_effort(db_session, monkeypatch):
    """邮件渠道失败不影响站内信落库,也不抛异常"""
    calls = []
    monkeypatch.setattr(
        notification_service, "notify",
        lambda email, title, content: calls.append((email, title)) or False,
    )
    user = _create_user(db_session, "ns_u2")
    ok = send_notification(db_session, user.id, "T", "C", "payment")
    assert ok is True
    assert calls == [(f"{user.username}@test.com", "T")]


@requires_db
def test_notify_ai_review_variants(db_session, monkeypatch):
    """三种AI裁决对应三种文案,type=ai_review"""
    monkeypatch.setattr(notification_service, "notify", lambda *a: False)
    user = _create_user(db_session, "ns_u3")
    expense = _create_expense(db_session, user)

    notification_service.notify_ai_review(db_session, expense, "auto_approve", "低风险")
    notification_service.notify_ai_review(db_session, expense, "auto_reject", "发票重复")
    notification_service.notify_ai_review(db_session, expense, "manual_review", "")

    rows = db_session.query(Notification).order_by(Notification.id).all()
    assert [r.type for r in rows] == ["ai_review"] * 3
    assert "自动通过" in rows[0].title
    assert "驳回" in rows[1].title and "发票重复" in rows[1].content
    assert "人工审批" in rows[2].title
    assert all(expense.expense_no in r.content for r in rows)


@requires_db
def test_notify_human_decision_and_payment(db_session, monkeypatch):
    monkeypatch.setattr(notification_service, "notify", lambda *a: False)
    user = _create_user(db_session, "ns_u4")
    expense = _create_expense(db_session, user, "EXP-TEST-0002")

    notify_human_decision(db_session, expense, approved=True, reason=None)
    notify_human_decision(db_session, expense, approved=False, reason="票据不全")
    notify_payment(db_session, expense)

    rows = db_session.query(Notification).order_by(Notification.id).all()
    assert "已通过" in rows[0].title
    assert "驳回" in rows[1].title and "票据不全" in rows[1].content
    assert rows[2].type == "payment" and "打款" in rows[2].title
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest backend/tests/test_services/test_notification_service.py -v`
Expected: ERROR/收集失败 `ModuleNotFoundError: No module named 'app.models.notification'`(DB 不可达时为 SKIP,此时以收集错误为准)

- [ ] **Step 3: 实现模型/模式/服务**

`backend/app/models/notification.py`:

```python
"""
站内通知数据模型
审核结果通知(AI审核/人工审批/打款登记)
"""
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, ForeignKey,
                        Integer, String, Text)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base


class Notification(Base):
    """
    站内通知表模型
    每条通知一行,按 user_id 隔离
    """

    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="收件人ID")
    title = Column(String(200), nullable=False, comment="通知标题")
    content = Column(Text, comment="通知内容")
    type = Column(String(20), default="system", nullable=False, comment="通知类型: ai_review/approval/payment")
    is_read = Column(Boolean, default=False, nullable=False, index=True, comment="是否已读")

    # server_default:与Expense.created_at同理,以数据库时钟为准
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间")

    user = relationship("User", backref="notifications")

    def __repr__(self):
        return f"<Notification(id={self.id}, user_id={self.user_id}, title={self.title})>"
```

`backend/app/models/__init__.py` 改为:

```python
"""
数据模型包
"""
from app.models.base import Base
from app.models.user import User, UserRole
from app.models.expense import (Expense, ExpenseItem, Category,
                                ExpenseStatus, ExpenseType)
from app.models.approval import Approval, ApprovalAction
from app.models.rule import Rule, RuleType, RuleSeverity, RuleOperator
from app.models.notification import Notification

__all__ = [
    "Base", "User", "UserRole",
    "Expense", "ExpenseItem", "Category", "ExpenseStatus", "ExpenseType",
    "Approval", "ApprovalAction",
    "Rule", "RuleType", "RuleSeverity", "RuleOperator",
    "Notification",
]
```

`backend/app/schemas/notification.py`:

```python
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
    """通知列表响应(paginate结构 + 未读数)"""
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    unread_count: int
```

`backend/app/services/notification_service.py`:

```python
"""
通知服务
核心契约:站内信落库必有;邮件尽力而为(复用notification_tool,失败仅告警)
"""
import logging

from sqlalchemy.orm import Session

from app.models import Expense, Notification, User
from app.tools.notification_tool import notify

logger = logging.getLogger(__name__)


def send_notification(db: Session, user_id: int, title: str, content: str, ntype: str) -> bool:
    """
    发送通知:站内信落库(必有) + 邮件(尽力而为)

    Returns:
        bool: 站内信是否落库成功(邮件结果不影响返回值)
    """
    try:
        db.add(Notification(user_id=user_id, title=title, content=content, type=ntype))
        db.commit()
    except Exception as e:
        logger.warning(f"站内信落库失败: {e}")
        db.rollback()
        return False

    try:
        user = db.get(User, user_id)
        if user and user.email:
            notify(user.email, title, content)
    except Exception as e:
        logger.warning(f"邮件通知失败(不影响主流程): {e}")
    return True


def notify_ai_review(db: Session, expense: Expense, action: str, reason: str) -> None:
    """AI审核结果通知申请人"""
    no = expense.expense_no
    mapping = {
        "auto_approve": ("报销单自动通过", f"您的报销单 {no} 已通过AI审核,自动通过,等待财务打款。"),
        "auto_reject": ("报销单被驳回(AI审核)", f"您的报销单 {no} 未通过AI审核,已驳回。\n原因:{reason or '未提供'}"),
        "manual_review": ("报销单转人工审批", f"您的报销单 {no} 已转人工审批,请等待审批人处理。"),
    }
    title, content = mapping.get(action, ("报销单审核进展", f"您的报销单 {no} 审核状态更新:{action}"))
    send_notification(db, expense.user_id, title, content, "ai_review")


def notify_human_decision(db: Session, expense: Expense, approved: bool, reason: str | None) -> None:
    """人工审批结果通知申请人"""
    no = expense.expense_no
    if approved:
        title, content = "报销单已通过审批", f"您的报销单 {no} 已通过人工审批,等待财务打款。"
    else:
        title, content = "报销单被驳回", f"您的报销单 {no} 被审批人驳回。\n原因:{reason or '未填写'}"
    send_notification(db, expense.user_id, title, content, "approval")


def notify_payment(db: Session, expense: Expense) -> None:
    """打款登记完成通知申请人"""
    send_notification(
        db, expense.user_id, "报销款已打款",
        f"您的报销单 {expense.expense_no} 已完成打款登记,金额 {expense.total_amount} 元。",
        "payment",
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest backend/tests/test_services/test_notification_service.py -v`
Expected: 4 passed(无 DB 则 skipped)

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/notification.py backend/app/models/__init__.py backend/app/schemas/notification.py backend/app/services/notification_service.py backend/tests/test_services/test_notification_service.py
git commit -m "feat(notifications): 站内信模型与通知服务(邮件尽力而为)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 通知接口

**Files:**
- Create: `backend/app/api/endpoints/notifications.py`
- Modify: `backend/app/main.py`(路由挂载处)
- Test: `backend/tests/test_api/test_notifications.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest backend/tests/test_api/test_notifications.py -v`
Expected: 404 Not Found(路由不存在)

- [ ] **Step 3: 实现端点**

`backend/app/api/endpoints/notifications.py`:

```python
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
```

`backend/app/main.py` 路由挂载处修改(import 行与 include 行各加一项):

```python
from app.api.endpoints import (agent, approvals, auth, categories, expenses,  # noqa: E402
                               notifications, reports, rules, users)
```

```python
app.include_router(reports.router)
app.include_router(categories.router)
app.include_router(notifications.router)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest backend/tests/test_api/test_notifications.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/endpoints/notifications.py backend/app/main.py backend/tests/test_api/test_notifications.py
git commit -m "feat(notifications): 我的通知列表/未读数/标记已读接口" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 接线——人工审批与打款通知

**Files:**
- Modify: `backend/app/services/approval_service.py`(decide 尾部)
- Modify: `backend/app/services/expense_service.py`(pay_expense 尾部)
- Test: `backend/tests/test_api/test_notifications.py`(追加)

- [ ] **Step 1: 追加失败测试**(追加到 `test_notifications.py` 末尾)

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest backend/tests/test_api/test_notifications.py -v`
Expected: 新增 2 个用例 FAIL(total == 1 实际 0)

- [ ] **Step 3: 接线实现**

`approval_service.py` 顶部 import 区加:

```python
from app.services.notification_service import notify_human_decision
```

`decide()` 在 `db.commit()` / `db.refresh(expense)` 之后、`logger.info` 之前插入:

```python
    # 通知申请人(站内信必有、邮件尽力而为;任何失败不影响审批结果)
    try:
        notify_human_decision(db, expense, approved=req.action == "approve", reason=req.comment)
    except Exception as e:
        logger.warning(f"审批结果通知失败(不影响主流程): {e}")
```

`expense_service.py` 顶部 import 区加:

```python
from app.services.notification_service import notify_payment
```

`pay_expense()` 在 `db.commit()` / `db.refresh(expense)` 之后、`logger.info` 之前插入:

```python
    # 打款完成通知申请人(失败不影响登记结果)
    try:
        notify_payment(db, expense)
    except Exception as e:
        logger.warning(f"打款通知失败(不影响主流程): {e}")
```

- [ ] **Step 4: 运行确认通过(含回归)**

Run: `uv run pytest backend/tests/test_api/test_notifications.py backend/tests/test_api/test_approvals.py backend/tests/test_api/test_expenses.py -v`
Expected: 全部 passed(既有用例不回归)

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/approval_service.py backend/app/services/expense_service.py backend/tests/test_api/test_notifications.py
git commit -m "feat(notifications): 人工审批与打款登记触发申请人通知" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 接线——AI 审核通知

**Files:**
- Modify: `backend/app/agents/workflow.py`(run() 落库后)
- Test: `backend/tests/test_agents/test_workflow_notify.py`

- [ ] **Step 1: 写失败测试**

```python
"""
AI审核工作流接线测试
monkeypatch掉LangGraph图与知识库,不调用真实LLM,验证:状态落库 + 申请人收到通知
"""
import asyncio

from app.agents import workflow as wf
from app.models import ExpenseStatus, Notification

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "接线测试报销",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-WF-NOTIFY-001",
        }
    ],
}


class _FakeGraph:
    """替身图:固定返回低风险自动通过"""
    async def ainvoke(self, state, config=None):
        return {
            "risk": {"risk_score": 30.0, "risk_level": "low", "factors": []},
            "decision": {"action": "auto_approve", "reason": "低风险单据", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {"invoice_verified": True, "anomalies": [], "summary": ""},
            "errors": [],
        }


@requires_db
def test_workflow_notifies_and_transitions(client, db_session, monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )

    headers = register_and_login(client, "wf_n1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    assert client.post(f"/api/expenses/{expense_id}/submit", headers=headers).status_code == 200

    asyncio.run(wf.workflow.run(db_session, expense_id))

    expense = db_session.get(wf.Expense, expense_id)
    assert expense.status == ExpenseStatus.APPROVED
    assert float(expense.risk_score) == 30.0

    note = db_session.query(Notification).one()
    assert note.type == "ai_review"
    assert "自动通过" in note.title
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest backend/tests/test_agents/test_workflow_notify.py -v`
Expected: FAIL(query(Notification).one() 抛 NoResultFound——通知尚未发送)

- [ ] **Step 3: 接线实现**

`workflow.py` 顶部 import 区加:

```python
from app.services.notification_service import notify_ai_review
```

`run()` 中,在 `db.commit()`(第4步落库)之后、知识库回填 `try` 之前插入:

```python
        # 4.5 通知申请人(站内信必有、邮件尽力而为;失败不影响审核结果)
        try:
            notify_ai_review(db, expense, action, decision.get("reason", ""))
        except Exception as e:
            logger.warning(f"AI审核通知失败(不影响主流程): {e}")
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest backend/tests/test_agents/test_workflow_notify.py -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/workflow.py backend/tests/test_agents/test_workflow_notify.py
git commit -m "feat(notifications): AI审核完成自动通知申请人" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 报表 xlsx 导出(后端)

**Files:**
- Modify: `backend/app/services/report_service.py`(新增 export_report)
- Modify: `backend/app/api/endpoints/reports.py`(新增 /export)
- Test: `backend/tests/test_api/test_reports.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest backend/tests/test_api/test_reports.py -v`
Expected: 前 3 个 PASS/403 类直接通过(既有接口),`test_export_*` 2 个 FAIL(404)

- [ ] **Step 3: 实现导出**

`report_service.py` 文件末尾追加:

```python
def export_report(db: Session, months: int = 6) -> bytes:
    """
    导出报表Excel:总览/月度趋势/分类占比/报销明细 四个sheet
    """
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    summary = get_summary(db)
    trends = get_trends(db, months)
    by_category = get_by_category(db)

    wb = Workbook()
    header_font = Font(bold=True)

    def _style(ws):
        for cell in ws[1]:
            cell.font = header_font
        ws.freeze_panes = "A2"

    # Sheet1 总览
    ws = wb.active
    ws.title = "总览"
    ws.append(["指标", "数值"])
    ws.append(["报销单总数", summary["total"]])
    ws.append(["累计报销金额", summary["total_amount"]])
    ws.append(["平均风险分", summary["avg_risk_score"]])
    ws.append(["本月新增", summary["month_count"]])
    ws.append(["生成时间", summary["generated_at"]])
    _style(ws)

    # Sheet2 月度趋势
    ws = wb.create_sheet("月度趋势")
    ws.append(["月份", "单数", "金额"])
    for m in trends["months"]:
        ws.append([m["month"], m["count"], m["amount"]])
    _style(ws)

    # Sheet3 分类占比
    ws = wb.create_sheet("分类占比")
    ws.append(["类别", "金额", "笔数", "占比"])
    for c in by_category["categories"]:
        ws.append([c["name"], c["amount"], c["count"], c["ratio"]])
    _style(ws)

    # Sheet4 报销明细
    ws = wb.create_sheet("报销明细")
    ws.append(["报销单号", "申请人", "部门", "类型", "金额", "状态", "风险分", "提交时间", "通过时间"])
    for e in db.query(Expense).order_by(Expense.created_at.desc()).all():
        ws.append([
            e.expense_no,
            e.applicant_name,
            e.applicant_department,
            e.expense_type.value if e.expense_type else "",
            float(e.total_amount),
            e.status.value if e.status else "",
            float(e.risk_score) if e.risk_score is not None else None,
            e.submitted_at.strftime("%Y-%m-%d %H:%M") if e.submitted_at else None,
            e.approved_at.strftime("%Y-%m-%d %H:%M") if e.approved_at else None,
        ])
    _style(ws)

    # 列宽:按各列内容最大长度粗略自适应(CJK按2倍宽)
    for sheet in wb.worksheets:
        for col_idx, col in enumerate(sheet.columns, start=1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            sheet.column_dimensions[get_column_letter(col_idx)].width = min(width * 2 + 2, 60)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

`reports.py` 顶部 import 修改为:

```python
"""
报表接口
汇总统计、月度趋势、分类占比、Excel导出（finance/admin）
"""
from datetime import date
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DBSession, require_roles
from app.models import User, UserRole
from app.services import report_service
```

文件末尾追加端点:

```python
@router.get("/export")
def export(
    db: DBSession,
    current_user: ReportUser,
    months: int = Query(6, ge=1, le=24, description="趋势sheet统计月数"),
):
    """导出报表Excel(4个sheet: 总览/月度趋势/分类占比/报销明细)"""
    content = report_service.export_report(db, months)
    filename = quote(f"报表_{date.today().strftime('%Y%m%d')}.xlsx")
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest backend/tests/test_api/test_reports.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/report_service.py backend/app/api/endpoints/reports.py backend/tests/test_api/test_reports.py
git commit -m "feat(reports): 报表Excel导出(4 sheet, finance/admin)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 后端用户自我保护

**Files:**
- Modify: `backend/app/api/endpoints/users.py`
- Test: `backend/tests/test_api/test_users.py`

- [ ] **Step 1: 写失败测试**

```python
"""
用户管理接口测试
admin鉴权 + 角色修改 + 启停 + 自我保护
"""
from tests.conftest import register_and_login, requires_db


def _find_user(client, headers, username):
    users = client.get("/api/users", headers=headers).json()
    return next(u for u in users if u["username"] == username)


@requires_db
def test_list_requires_admin(client):
    resp = client.get("/api/users", headers=register_and_login(client, "us_e1"))
    assert resp.status_code == 403


@requires_db
def test_admin_cannot_modify_self(client):
    """自我保护:改自己角色/状态都返回400"""
    headers = register_and_login(client, "us_admin1", role="admin")
    me = _find_user(client, headers, "us_admin1")
    resp = client.patch(
        f"/api/users/{me['id']}/role", json={"role": "employee"}, headers=headers
    )
    assert resp.status_code == 400
    resp = client.patch(
        f"/api/users/{me['id']}/status", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 400


@requires_db
def test_admin_can_modify_other(client):
    headers = register_and_login(client, "us_admin2", role="admin")
    register_and_login(client, "us_emp2")
    other = _find_user(client, headers, "us_emp2")

    resp = client.patch(
        f"/api/users/{other['id']}/role", json={"role": "manager"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"

    resp = client.patch(
        f"/api/users/{other['id']}/status", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@requires_db
def test_get_404(client):
    headers = register_and_login(client, "us_admin3", role="admin")
    resp = client.get("/api/users/99999", headers=headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest backend/tests/test_api/test_users.py -v`
Expected: `test_admin_cannot_modify_self` FAIL(当前返回 200)

- [ ] **Step 3: 实现自我保护**

`users.py` 的 `update_role` 中,`user = _get_user_or_404(db, user_id)` 之后加:

```python
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
```

`update_status` 中,`user = _get_user_or_404(db, user_id)` 之后加:

```python
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的状态(避免误禁用自己)")
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest backend/tests/test_api/test_users.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/endpoints/users.py backend/tests/test_api/test_users.py
git commit -m "feat(users): 用户管理接口补自我保护与测试" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 前端——通知类型、API 与顶栏铃铛

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/notification.ts`
- Modify: `frontend/src/layout/MainLayout.vue`

- [ ] **Step 1: types/index.ts 末尾追加类型**

```typescript
// ========== 站内通知 ==========
export type NotificationType = 'ai_review' | 'approval' | 'payment' | 'system'

export interface NotificationItem {
  id: number
  user_id: number
  title: string
  content: string | null
  type: NotificationType
  is_read: boolean
  created_at: string
}

// 后端通知列表 = paginate结构 + unread_count
export interface NotificationPage extends PageResult<NotificationItem> {
  unread_count: number
}
```

- [ ] **Step 2: 新建 api/notification.ts**

```typescript
// 站内通知 API
import request from '@/utils/request'
import type { NotificationItem, NotificationPage, NotificationType } from '@/types'

export function getNotifications(page = 1, pageSize = 10): Promise<NotificationPage> {
  return request.get('/notifications', { params: { page, page_size: pageSize } })
}

export function getUnreadCount(): Promise<{ count: number }> {
  return request.get('/notifications/unread-count')
}

export function markRead(id: number): Promise<NotificationItem> {
  return request.post(`/notifications/${id}/read`)
}

export function markAllRead(): Promise<{ updated: boolean }> {
  return request.post('/notifications/read-all')
}

// 通知类型 → 标签文案/颜色(铃铛下拉用)
export const TYPE_LABELS: Record<string, string> = {
  ai_review: 'AI审核',
  approval: '审批',
  payment: '打款',
  system: '系统',
}

export const TYPE_TAG_TYPES: Record<NotificationType, 'success' | 'warning' | 'info'> = {
  ai_review: 'warning',
  approval: 'success',
  payment: 'info',
  system: 'info',
}
```

- [ ] **Step 3: MainLayout.vue 加铃铛**

`<script setup>` 中,现有 import 之后追加:

```typescript
import { onMounted, onUnmounted } from 'vue'
import { Bell } from '@element-plus/icons-vue'
import {
  TYPE_LABELS,
  TYPE_TAG_TYPES,
  getNotifications,
  getUnreadCount,
  markAllRead,
  markRead,
} from '@/api/notification'
import type { NotificationItem } from '@/types'

// ===== 站内通知 =====
const unreadCount = ref(0)
const notifications = ref<NotificationItem[]>([])
let notifyTimer: ReturnType<typeof setInterval> | undefined

async function loadUnread() {
  try {
    unreadCount.value = (await getUnreadCount()).count
  } catch {
    /* 轮询失败静默 */
  }
}

async function loadNotifications() {
  try {
    notifications.value = (await getNotifications(1, 10)).items
  } catch {
    /* 静默 */
  }
}

async function readOne(n: NotificationItem) {
  if (n.is_read) return
  await markRead(n.id)
  n.is_read = true
  unreadCount.value = Math.max(0, unreadCount.value - 1)
}

async function readAll() {
  await markAllRead()
  notifications.value.forEach((n) => (n.is_read = true))
  unreadCount.value = 0
}

function formatNotifyTime(iso: string) {
  return iso.replace('T', ' ').slice(0, 16)
}
```

注意:文件顶部已有 `import { computed } from 'vue'`,把 `ref` 等合并进同一行:`import { computed, onMounted, onUnmounted, ref } from 'vue'`,并删除上面代码块的第一行重复 import。末尾 `</script>` 前追加生命周期:

```typescript
onMounted(() => {
  loadUnread()
  notifyTimer = setInterval(loadUnread, 30000)
})
onUnmounted(() => notifyTimer && clearInterval(notifyTimer))
```

模板中,`<el-header>` 内的用户 `el-dropdown` 之前插入(并把「标题 + 右侧两元素」用 div 包裹对齐):

```vue
        <div class="header-right">
          <!-- 站内通知 -->
          <el-dropdown class="notify-drop" @visible-change="(v: boolean) => v && loadNotifications()">
            <span class="notify-bell">
              <el-badge :value="unreadCount" :hidden="!unreadCount" :max="99">
                <el-icon :size="18"><Bell /></el-icon>
              </el-badge>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <div v-if="!notifications.length" class="notify-empty">暂无通知</div>
                <div
                  v-for="n in notifications"
                  :key="n.id"
                  class="notify-item"
                  :class="{ unread: !n.is_read }"
                  @click="readOne(n)"
                >
                  <div class="notify-title">
                    <el-tag size="small" :type="TYPE_TAG_TYPES[n.type] || 'info'">
                      {{ TYPE_LABELS[n.type] || n.type }}
                    </el-tag>
                    <span>{{ n.title }}</span>
                  </div>
                  <div class="notify-content">{{ n.content }}</div>
                  <div class="notify-time">{{ formatNotifyTime(n.created_at) }}</div>
                </div>
                <div v-if="notifications.length" class="notify-footer" @click="readAll">
                  全部已读
                </div>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-dropdown @command="handleCommand"> ...原用户下拉保持不变... </el-dropdown>
        </div>
```

即:原有的用户 `el-dropdown` 整块移入 `<div class="header-right">`,铃铛下拉在前。样式区追加:

```scss
.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.notify-bell {
  display: flex;
  align-items: center;
  cursor: pointer;
  outline: none;
}

.notify-drop :deep(.el-dropdown-menu) {
  width: 320px;
  max-height: 400px;
  overflow-y: auto;
  padding: 4px 0;
}

.notify-empty {
  padding: 24px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}

.notify-item {
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid #f0f2f5;

  &:hover {
    background: #f5f7fa;
  }

  &.unread .notify-title span {
    font-weight: 600;
  }

  .notify-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #303133;
  }

  .notify-content {
    margin-top: 4px;
    font-size: 12px;
    color: #909399;
    white-space: pre-line;
  }

  .notify-time {
    margin-top: 2px;
    font-size: 12px;
    color: #c0c4cc;
  }
}

.notify-footer {
  padding: 10px 0;
  text-align: center;
  font-size: 13px;
  color: #409eff;
  cursor: pointer;
}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: vue-tsc 无错误,vite 构建成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/notification.ts frontend/src/layout/MainLayout.vue
git commit -m "feat(frontend): 顶栏通知铃铛(未读数轮询+下拉已读)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: 前端——报表导出按钮

**Files:**
- Modify: `frontend/src/api/report.ts`
- Modify: `frontend/src/views/ReportsView.vue`

- [ ] **Step 1: api/report.ts 追加导出函数**

```typescript
// 导出报表Excel(blob下载;拦截器已返回response.data,此处即Blob)
export async function exportReport(months = 6): Promise<void> {
  const blob = (await request.get('/reports/export', {
    params: { months },
    responseType: 'blob',
  })) as Blob
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `报表_${new Date().toISOString().slice(0, 10)}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 2: ReportsView.vue 加按钮**

`<script setup>` 中,现有 import 之后追加:

```typescript
import { Download } from '@element-plus/icons-vue'
import { exportReport } from '@/api/report'

const exporting = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    await exportReport(6)
  } finally {
    exporting.value = false
  }
}
```

(`Download` 图标局部引入;`ref` 已在文件 import 中。)

模板 `page-header` 中,刷新按钮之前插入:

```vue
      <el-button type="success" :loading="exporting" @click="handleExport">
        <el-icon><Download /></el-icon>&nbsp;导出 Excel
      </el-button>
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/report.ts frontend/src/views/ReportsView.vue
git commit -m "feat(frontend): 报表页导出Excel按钮" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: 前端——用户管理页面

**Files:**
- Create: `frontend/src/api/user.ts`
- Create: `frontend/src/views/UserManagementView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layout/MainLayout.vue`(菜单)

- [ ] **Step 1: 新建 api/user.ts**

```typescript
// 用户管理 API(admin)
import request from '@/utils/request'
import type { UserInfo, UserRole } from '@/types'

// 后端list接口返回裸数组(无分页包装),取前100条够用
export function getUsers(role?: UserRole): Promise<UserInfo[]> {
  return request.get('/users', { params: { page: 1, page_size: 100, role } })
}

export function updateUserRole(id: number, role: UserRole): Promise<UserInfo> {
  return request.patch(`/users/${id}/role`, { role })
}

export function updateUserStatus(id: number, isActive: boolean): Promise<UserInfo> {
  return request.patch(`/users/${id}/status`, { is_active: isActive })
}
```

- [ ] **Step 2: 新建 views/UserManagementView.vue**

```vue
<script setup lang="ts">
// 用户管理(admin):列表 / 角色筛选 / 改角色 / 启停
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUsers, updateUserRole, updateUserStatus } from '@/api/user'
import { useUserStore } from '@/stores/user'
import type { UserInfo, UserRole } from '@/types'

const userStore = useUserStore()
const loading = ref(true)
const users = ref<UserInfo[]>([])
const roleFilter = ref<UserRole | ''>('')

const roleOptions: { value: UserRole; label: string }[] = [
  { value: 'admin', label: '管理员' },
  { value: 'finance', label: '财务' },
  { value: 'manager', label: '经理' },
  { value: 'employee', label: '员工' },
]

function roleLabel(role: UserRole) {
  return roleOptions.find((r) => r.value === role)?.label || role
}

async function load() {
  loading.value = true
  try {
    users.value = await getUsers(roleFilter.value || undefined)
  } finally {
    loading.value = false
  }
}

// 自己的行:下拉/开关禁用(后端也有双保险)
function isSelf(u: UserInfo) {
  return u.id === userStore.user?.id
}

async function handleRoleChange(u: UserInfo, role: UserRole) {
  const old = u.role
  try {
    await ElMessageBox.confirm(
      `确定将 ${u.full_name || u.username} 的角色由「${roleLabel(old)}」改为「${roleLabel(role)}」吗?`,
      '修改角色',
      { type: 'warning' },
    )
  } catch {
    u.role = old // 取消则还原下拉
    return
  }
  Object.assign(u, await updateUserRole(u.id, role))
  ElMessage.success('角色已更新')
}

async function handleStatusChange(u: UserInfo, active: boolean) {
  try {
    Object.assign(u, await updateUserStatus(u.id, active))
    ElMessage.success(active ? '已启用' : '已禁用')
  } catch {
    u.is_active = !active // 失败还原开关
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>用户管理</h2>
      <el-select
        v-model="roleFilter"
        placeholder="全部角色"
        clearable
        style="width: 160px"
        @change="load"
      >
        <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
      </el-select>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="users" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column label="姓名" min-width="100">
          <template #default="{ row }">{{ row.full_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column label="部门" min-width="100">
          <template #default="{ row }">{{ row.department || '-' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="150">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              :disabled="isSelf(row)"
              size="small"
              @change="handleRoleChange(row, $event as UserRole)"
            >
              <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              :disabled="isSelf(row)"
              @change="handleStatusChange(row, $event as boolean)"
            />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            {{ row.created_at?.replace('T', ' ').slice(0, 16) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
```

- [ ] **Step 3: 路由注册**(router/index.ts,rules 路由之后)

```typescript
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UserManagementView.vue'),
        meta: { title: '用户管理', roles: ['admin'] },
      },
```

- [ ] **Step 4: 菜单项**(MainLayout.vue 的 menus 数组,rules 项之后)

```typescript
    { path: '/users', title: '用户管理', icon: 'User', roles: ['admin'] },
```

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/user.ts frontend/src/views/UserManagementView.vue frontend/src/router/index.ts frontend/src/layout/MainLayout.vue
git commit -m "feat(frontend): admin用户管理页面(改角色/启停/自我保护禁用)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: 收尾——全量回归 + README 更新

- [ ] **Step 1: 后端全量测试**

Run: `uv run pytest -v`
Expected: 全部 passed / skipped(无 DB 时 DB 用例 skip),无新增 FAIL

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 更新 README.md 的 Work in Progress 三行**

| 📧 Review notifications | ✅ Done | In-app bell notifications (30s polling) + best-effort email on AI review / human decision / payment |
| 📤 Report export | ✅ Done | `GET /api/reports/export` returns a 4-sheet xlsx (summary / trends / by-category / details); finance/admin |
| 👥 User management UI | ✅ Done | `/users` page for admin: role change + enable/disable, self-modification blocked |

- [ ] **Step 4: README.zh-CN.md 对应三行同步为中文**

| 📧 审核结果通知 | ✅ 已完成 | 站内信铃铛(30秒轮询)+ 邮件尽力而为;AI审核/人工审批/打款登记三个触发点 |
| 📤 报表导出 | ✅ 已完成 | `GET /api/reports/export` 返回4-sheet xlsx(总览/趋势/分类/明细);finance/admin |
| 👥 用户管理页面 | ✅ 已完成 | `/users` admin页面:改角色/启停,禁止操作自己 |

- [ ] **Step 5: 提交**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: 阶段①完成——通知/导出/用户管理页从WIP表移除" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 验收(对照规格阶段①)

1. 提交报销单触发 AI 审核(monkeypatch 验证)→ 申请人铃铛有 ai_review 通知;人工审批/打款同样产生通知
2. 通知接口:未登录 401、跨用户隔离、已读流转正确
3. finance 导出 xlsx 成功、employee 403;文件可被 Excel 打开
4. admin 在 /users 页面改角色需确认、启停生效;自己一行控件禁用且后端 400 双保险
5. `uv run pytest` 与 `npm run build` 全绿
