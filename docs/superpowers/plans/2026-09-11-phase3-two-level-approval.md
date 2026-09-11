# 阶段③ 实施计划：两级审批链（经理初审 → 财务终审）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地规格 [2026-09-09-unfinished-features-design.md](../specs/2026-09-09-unfinished-features-design.md) 的阶段③——固定两级审批链：AI 转人工后经理初审（本部门）→ 财务终审，任一级可驳回，admin 可越级直批兜底，无经理部门自动跳过初审。

**Architecture:** 新增 `ExpenseStatus.MANAGER_APPROVED` 状态与 `approvals.step` 层级列（manager/finance），`approval_service.decide` 按角色×状态重写为规则表；`workflow.py` 落库时按确定性规则（申请人是经理 / 部门无在职经理）决定落 PENDING 还是直接跳到 MANAGER_APPROVED（留痕）。无 Alembic，提供幂等迁移（逻辑在 `app/db_migrations.py` 可测，`scripts/migrate_v2.py` 为 CLI 薄壳）。前端审批中心分「待初审 / 待终审」两组、按角色显隐操作按钮，时间线按 step 渲染「初审通过（经理）/ 终审通过（财务）」。

**Tech Stack:** SQLAlchemy(Enum 扩展) · FastAPI · Vue3(el-tabs) · 已有测试基建

**重要约束:**
- 后端测试命令（在 `backend/` 目录执行）：
  `TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest <路径> -v`
- 测试注册用户默认部门「测试部」（conftest register_and_login），manager 与 employee 同部门可直接互审
- 测试中 `AGENT_REVIEW_ON_SUBMIT=False`：submit 后状态停在 SUBMITTED，测试用 db 直改 PENDING 模拟 AI 转人工
- 前端验证 `cd frontend && npm run build`
- `cancel_expense` 现状已只允许 DRAFT/SUBMITTED/PENDING，无需改代码，只补测试

---

## 文件结构

| 动作 | 文件 | 职责 |
|---|---|---|
| Modify | `backend/app/models/expense.py` | ExpenseStatus 增 MANAGER_APPROVED |
| Modify | `backend/app/models/approval.py` | Approval 增 step 列 |
| Create | `backend/app/db_migrations.py` | migrate_v2(engine) 幂等迁移（可单测） |
| Create | `backend/scripts/migrate_v2.py` | CLI 薄壳（读 settings.DATABASE_URL 或 --url） |
| Modify | `backend/app/schemas/approval.py` | ApprovalResponse.step、PendingExpenseItem.status |
| Modify | `backend/app/services/approval_service.py` | decide 规则表重写、list_pending 双状态 |
| Modify | `backend/app/services/notification_service.py` | notify_human_decision 增 step 参数分文案 |
| Modify | `backend/app/agents/workflow.py` | manual_review 落库按跳过规则分流 |
| Modify | `frontend/src/types/index.ts` | ExpenseStatus/ApprovalRecord/PendingExpense |
| Modify | `frontend/src/constants/index.ts` | STATUS_MAP 增 manager_approved |
| Modify | `frontend/src/views/ApprovalCenterView.vue` | 分待初审/待终审两组+角色显隐按钮 |
| Modify | `frontend/src/components/ExpenseDetailDrawer.vue` | actionLabel 按 step 渲染初审/终审 |
| Modify | `README.md` / `README.zh-CN.md` | 107 行改 ✅ |
| Test | `backend/tests/test_migrations/test_migrate_v2.py`、`tests/test_api/test_approvals.py`(重写扩充)、`tests/test_agents/test_workflow_skip.py`、`tests/test_api/test_expenses.py`(+1取消用例) | 本阶段用例 |

状态机（规格原文）：

```
SUBMITTED ──AI auto_approve──→ APPROVED（不变）
        ├─AI auto_reject───→ REJECTED（不变）
        └─AI manual_review─→ PENDING（待经理初审）
                               │ manager approve → MANAGER_APPROVED（待财务终审）
                               │                    │ finance/admin approve → APPROVED（写 approved_at）
                               └── 任一级 reject ──→ REJECTED（可改后重提）
```

---

### Task 0: 前置准备

- [ ] **Step 1: 创建功能分支**

```bash
git checkout -b feat/phase3-two-level-approval
```

---

### Task 1: 模型 + 迁移

**Files:**
- Modify: `backend/app/models/expense.py`
- Modify: `backend/app/models/approval.py`
- Create: `backend/app/db_migrations.py`
- Create: `backend/scripts/migrate_v2.py`
- Test: `backend/tests/test_migrations/test_migrate_v2.py`

- [ ] **Step 1: 写失败测试**

```python
"""
migrate_v2 幂等迁移测试：approvals.step 列存在、expenses.status 枚举含 manager_approved、
重复执行不报错（需测试DB）
"""
from sqlalchemy import inspect, text

from app.db_migrations import migrate_v2

from tests.conftest import requires_db


@requires_db
def test_migrate_v2_idempotent(db_session):
    engine = db_session.get_bind()
    migrate_v2(engine)   # 第二次执行不应报错（列已存在时跳过）
    migrate_v2(engine)

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("approvals")}
    assert "step" in cols

    # status 列类型已扩展（MySQL ENUM 文本包含新值）
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                 "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='expenses' "
                 "AND COLUMN_NAME='status'")
        ).scalar()
    assert "manager_approved" in row
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest tests/test_migrations/ -v`
Expected: 收集失败 `ModuleNotFoundError: No module named 'app.db_migrations'`

- [ ] **Step 3: 实现**

`backend/app/models/expense.py` 枚举加一行（PENDING 之后）：

```python
    PENDING = "pending"           # 审核中
    MANAGER_APPROVED = "manager_approved"  # 经理已初审，待财务终审
    APPROVED = "approved"         # 已通过
```

`backend/app/models/approval.py`：import 行加 `String` 已有；`comment` 列之后加：

```python
    action = Column(Enum(ApprovalAction), nullable=False, comment="审批动作")
    comment = Column(Text, comment="审批意见/AI审核说明")
    # 审批层级（仅人工 APPROVE/REJECT 时记录）：manager=初审 finance=终审
    step = Column(String(20), comment="审批层级: manager/finance")
```

`backend/app/db_migrations.py`（新建）：

```python
"""
v2 幂等迁移：两级审批链
1) expenses.status 枚举追加 manager_approved
2) approvals 表新增 step 列（可重复执行，已存在则跳过）
项目未用 Alembic，手动 DDL 按方言分派；新库经 init_db.py 建表即为新结构，无需本脚本
"""
import logging
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# 与 ExpenseStatus 枚举成员保持一致（顺序即 DDL 顺序）
_STATUS_VALUES = (
    "draft", "submitted", "pending", "manager_approved",
    "approved", "rejected", "paid", "cancelled",
)


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {"t": table, "c": column}).scalar()
    return bool(row)


def migrate_v2(engine: Engine) -> None:
    """幂等执行 v2 迁移（MySQL / PostgreSQL）"""
    with engine.begin() as conn:
        dialect = engine.dialect.name

        # 1) expenses.status 追加 manager_approved
        conn.execute(text(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='expenses' AND COLUMN_NAME='status'"
        ))
        if dialect == "mysql":
            values = ", ".join(f"'{v}'" for v in _STATUS_VALUES)
            conn.execute(text(
                f"ALTER TABLE expenses MODIFY status ENUM({values}) NOT NULL"
            ))
        else:  # postgresql：枚举追加需 ADD VALUE（不支持在事务内 IF NOT EXISTS 的老版本逐个处理）
            conn.execute(text(
                "ALTER TYPE expensestatus ADD VALUE IF NOT EXISTS 'manager_approved'"
            ))

        # 2) approvals.step 列
        if not _column_exists(conn, "approvals", "step"):
            if dialect == "mysql":
                conn.execute(text(
                    "ALTER TABLE approvals ADD COLUMN step VARCHAR(20) NULL "
                    "COMMENT '审批层级: manager/finance'"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS step VARCHAR(20) NULL"
                ))
        logger.info("migrate_v2 完成（expenses.status + approvals.step）")
```

注意：PG 的 `ALTER TYPE ... ADD VALUE` 不能在事务块内执行（engine.begin 会包事务）。为保持简单：本项目 dev/test 均为 MySQL，`db_migrations.py` 里 PG 分支仅作尽力而为（用 `conn.execution_options(isolation_level="AUTOCOMMIT")` 的 engine 副本执行 ADD VALUE）；实现时若 PG 分支复杂化，允许只保留 MySQL 分支 + 对 PG raise NotImplementedError 提示走重建库路线（规格允许：开发库可直接重建）。以实际可测的 MySQL 路径为准，不为准测不了的方言写假代码。

`backend/scripts/migrate_v2.py`（新建，CLI 薄壳）：

```python
"""
v2 迁移 CLI：python scripts/migrate_v2.py [--url DATABASE_URL]
默认用 app 配置的 DATABASE_URL
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.db_migrations import migrate_v2  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="两级审批链 v2 幂等迁移")
    parser.add_argument("--url", default=None, help="数据库连接串（默认取 .env 的 DATABASE_URL）")
    args = parser.parse_args()
    url = args.url or settings.DATABASE_URL
    engine = create_engine(url)
    try:
        migrate_v2(engine)
        print("migrate_v2 完成")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_migrations/ -v`（前缀同上）
Expected: 1 passed

- [ ] **Step 5: 对开发库执行迁移**

```bash
cd backend && uv run python scripts/migrate_v2.py
```
Expected: 输出 `migrate_v2 完成`

- [ ] **Step 6: 提交**

```bash
git add backend/app/models backend/app/db_migrations.py backend/scripts/migrate_v2.py backend/tests/test_migrations
git commit -m "feat(approval): manager_approved状态+approvals.step列+幂等迁移" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: decide 规则表重写 + list_pending 双状态 + schema

**Files:**
- Modify: `backend/app/services/approval_service.py`
- Modify: `backend/app/schemas/approval.py`
- Modify: `backend/tests/test_api/test_approvals.py`（重写+扩充）
- Modify: `backend/tests/test_api/test_expenses.py`（+1 取消用例）

- [ ] **Step 1: 重写测试文件（整文件替换 test_approvals.py）**

```python
"""
审批接口测试（需测试DB）：两级审批链
经理初审(Pending→ManagerApproved) → 财务终审(→Approved)；admin越级；任一级驳回
"""
from app.models import Expense, ExpenseStatus

from tests.conftest import register_and_login, requires_db

EXPENSE_PAYLOAD = {
    "title": "招待费报销",
    "expense_type": "meal",
    "description": "客户招待",
    "items": [
        {
            "category_id": 2,
            "description": "客户工作餐",
            "amount": "380.00",
            "expense_date": "2026-08-25",
            "invoice_no": "INV11112222",
        }
    ],
}


def _create_pending(client, db_session, username, status=ExpenseStatus.PENDING):
    """创建报销单并直改状态（模拟AI转人工），返回(单据ID, 申请人headers)"""
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    expense = db_session.get(Expense, expense_id)
    expense.status = status
    db_session.commit()
    return expense_id, headers


def _decide(client, headers, expense_id, action="approve", comment=None):
    return client.post(
        "/api/approvals/decide",
        json={"expense_id": expense_id, "action": action, "comment": comment},
        headers=headers,
    )


@requires_db
def test_employee_cannot_decide(client, db_session):
    """employee无审批权：decide 403、pending列表403"""
    expense_id, _ = _create_pending(client, db_session, "ap_e1")
    headers = register_and_login(client, "ap_emp")
    assert _decide(client, headers, expense_id).status_code == 403
    assert client.get("/api/approvals/pending", headers=headers).status_code == 403


@requires_db
def test_two_level_chain(client, db_session):
    """完整链：经理初审→manager_approved(step=manager)→财务终审→approved(step=finance,approved_at)"""
    expense_id, owner_headers = _create_pending(client, db_session, "ap_e2")
    manager_headers = register_and_login(client, "ap_mgr2", role="manager")
    finance_headers = register_and_login(client, "ap_fin2", role="finance")

    resp = _decide(client, manager_headers, expense_id, comment="初审通过")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "manager_approved"

    resp = _decide(client, finance_headers, expense_id, comment="终审通过")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    resp = client.get(f"/api/approvals/{expense_id}/history", headers=owner_headers)
    items = resp.json()["items"]
    steps = [(a["action"], a["step"]) for a in items if a["action"] == "approve"]
    assert ("approve", "manager") in steps and ("approve", "finance") in steps

    body = client.get(f"/api/expenses/{expense_id}", headers=owner_headers).json()
    assert body["approved_at"] is not None


@requires_db
def test_manager_reject(client, db_session):
    """经理初审驳回→rejected，原因落库"""
    expense_id, owner_headers = _create_pending(client, db_session, "ap_e3")
    manager_headers = register_and_login(client, "ap_mgr3", role="manager")
    assert _decide(client, manager_headers, expense_id, action="reject", comment="票据不齐").status_code == 200
    body = client.get(f"/api/expenses/{expense_id}", headers=owner_headers).json()
    assert body["status"] == "rejected" and "票据不齐" in (body["rejection_reason"] or "")


@requires_db
def test_finance_reject_at_final(client, db_session):
    """财务终审阶段驳回→rejected"""
    expense_id, _ = _create_pending(client, db_session, "ap_e4")
    manager_headers = register_and_login(client, "ap_mgr4", role="manager")
    finance_headers = register_and_login(client, "ap_fin4", role="finance")
    _decide(client, manager_headers, expense_id)
    assert _decide(client, finance_headers, expense_id, action="reject", comment="超预算").status_code == 200
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.REJECTED


@requires_db
def test_finance_cannot_first_review(client, db_session):
    """财务不可操作PENDING（须先过经理初审）→400"""
    expense_id, _ = _create_pending(client, db_session, "ap_e5")
    finance_headers = register_and_login(client, "ap_fin5", role="finance")
    resp = _decide(client, finance_headers, expense_id)
    assert resp.status_code == 400
    assert "初审" in resp.json()["detail"]


@requires_db
def test_admin_override_approve(client, db_session):
    """admin越级直批PENDING→approved（留痕step=finance）"""
    expense_id, _ = _create_pending(client, db_session, "ap_e6")
    admin_headers = register_and_login(client, "ap_adm6", role="admin")
    resp = _decide(client, admin_headers, expense_id, comment="紧急，越级直批")
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    items = client.get(
        f"/api/approvals/{expense_id}/history", headers=admin_headers
    ).json()["items"]
    rec = next(a for a in items if a["action"] == "approve")
    assert rec["step"] == "finance" and "越级" in (rec["comment"] or "")


@requires_db
def test_manager_cannot_final_review(client, db_session):
    """manager不可终审（不在其可操作状态）→400"""
    expense_id, _ = _create_pending(client, db_session, "ap_e7")
    manager_headers = register_and_login(client, "ap_mgr7", role="manager")
    resp = _decide(client, manager_headers, expense_id)
    assert resp.status_code == 200  # 初审通过
    resp = _decide(client, manager_headers, expense_id)  # 再操作manager_approved
    assert resp.status_code == 400


@requires_db
def test_cannot_decide_submitted(client, db_session):
    """SUBMITTED（未进人工链）任何人不可审→400"""
    headers = register_and_login(client, "ap_e8")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    admin_headers = register_and_login(client, "ap_adm8", role="admin")
    assert _decide(client, admin_headers, expense_id).status_code == 400


@requires_db
def test_manager_other_department_403(client, db_session):
    """manager不能审其他部门：注册后改库中部门实现跨部门"""
    from app.models import User
    expense_id, _ = _create_pending(client, db_session, "ap_e9")
    other_headers = register_and_login(client, "ap_mgr9", role="manager")
    other = db_session.query(User).filter(User.username == "ap_mgr9").first()
    other.department = "别的部门"
    db_session.commit()
    assert _decide(client, other_headers, expense_id).status_code == 403


@requires_db
def test_list_pending_scopes(client, db_session):
    """manager见PENDING(本部门)；finance/admin见PENDING+MANAGER_APPROVED"""
    pending_id, _ = _create_pending(client, db_session, "ap_e10")
    final_id, _ = _create_pending(
        client, db_session, "ap_e10b", status=ExpenseStatus.MANAGER_APPROVED
    )
    manager_headers = register_and_login(client, "ap_mgr10", role="manager")
    ids = [e["id"] for e in client.get("/api/approvals/pending", headers=manager_headers).json()]
    assert pending_id in ids and final_id not in ids
    # 返回项带status，前端分组用
    statuses = {e["id"]: e["status"] for e in client.get("/api/approvals/pending", headers=manager_headers).json()}
    assert statuses[pending_id] == "pending"

    finance_headers = register_and_login(client, "ap_fin10", role="finance")
    ids = [e["id"] for e in client.get("/api/approvals/pending", headers=finance_headers).json()]
    assert pending_id in ids and final_id in ids
```

并在 `backend/tests/test_api/test_expenses.py` 文件末尾追加：

```python
@requires_db
def test_cancel_after_manager_approved_forbidden(client, db_session):
    """MANAGER_APPROVED（已进财务队列）不可自行取消→400"""
    from app.models import Expense, ExpenseStatus
    headers = register_and_login(client, "cx_e1")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    expense = db_session.get(Expense, expense_id)
    expense.status = ExpenseStatus.MANAGER_APPROVED
    db_session.commit()
    resp = client.post(f"/api/expenses/{expense_id}/cancel", headers=headers)
    assert resp.status_code == 400
```

（test_expenses.py 若无 `EXPENSE_PAYLOAD`/`requires_db` 导入，追加时补齐导入；写实现时以文件现状为准。）

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_api/test_approvals.py tests/test_api/test_expenses.py -v`
Expected: 大面积 FAIL（finance直批现可成功、无step字段、manager无法审等）

- [ ] **Step 3: 实现**

`backend/app/schemas/approval.py`：ApprovalResponse 加字段（`comment` 行后）：

```python
    comment: Optional[str] = None
    step: Optional[str] = None  # 审批层级: manager/finance（人工审批记录）
```

PendingExpenseItem 加字段（`id` 行后）：

```python
    id: int
    status: ExpenseStatus
    expense_no: str
```

（文件顶部 import：`from app.models.expense import ExpenseStatus`。）

`backend/app/services/approval_service.py` —— `list_pending` 与 `decide` 整体替换为：

```python
def list_pending(db: Session, user: User) -> List[Expense]:
    """
    待审批列表（两级链）：
    manager 见 PENDING（本部门）；finance/admin 见 PENDING + MANAGER_APPROVED
    """
    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    query = db.query(Expense).filter(
        Expense.status.in_([ExpenseStatus.PENDING, ExpenseStatus.MANAGER_APPROVED])
    )
    # manager 只审本部门；finance/admin 审全部
    if user.role == UserRole.MANAGER:
        from app.models.user import User as UserModel
        query = query.join(UserModel, Expense.user_id == UserModel.id).filter(
            UserModel.department == user.department,
            Expense.status == ExpenseStatus.PENDING,
        )
    return query.order_by(Expense.submitted_at.asc()).all()


def decide(db: Session, user: User, req: ApprovalDecisionRequest) -> Expense:
    """
    两级审批决策（规则表）：
    manager: PENDING(本部门) approve→MANAGER_APPROVED / reject→REJECTED
    finance: MANAGER_APPROVED approve→APPROVED(写approved_at) / reject→REJECTED
    admin:   PENDING/MANAGER_APPROVED 越级直批→APPROVED（留痕）/ reject→REJECTED
    """
    if not user.has_permission("approve"):
        raise HTTPException(status_code=403, detail="无审批权限")

    expense = db.query(Expense).filter(Expense.id == req.expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail=f"报销单 {req.expense_id} 不存在")

    # 角色可操作状态表
    if user.role == UserRole.MANAGER:
        allowed = {ExpenseStatus.PENDING}
    elif user.role == UserRole.FINANCE:
        allowed = {ExpenseStatus.MANAGER_APPROVED}
    else:  # admin：越级兜底，两级状态都可操作
        allowed = {ExpenseStatus.PENDING, ExpenseStatus.MANAGER_APPROVED}

    if expense.status not in allowed:
        hint = {
            UserRole.FINANCE: "财务终审需先经经理初审（当前状态 {s}）",
            UserRole.MANAGER: "当前状态 {s} 不可初审（仅待经理初审的单可操作）",
        }.get(user.role, "当前状态 {s} 不可审批")
        raise HTTPException(status_code=400, detail=hint.format(s=expense.status.value))

    # manager 只能审本部门的单
    if user.role == UserRole.MANAGER:
        owner = expense.user
        if not owner or owner.department != user.department:
            raise HTTPException(status_code=403, detail="只能审批本部门的报销单")

    comment = req.comment
    if req.action == "approve":
        # step：初审(manager)停在 MANAGER_APPROVED；到达 APPROVED 记 finance（admin越级同样记finance）
        is_first_review = (
            user.role == UserRole.MANAGER and expense.status == ExpenseStatus.PENDING
        )
        step = "manager" if is_first_review else "finance"
        if user.role == UserRole.ADMIN and expense.status == ExpenseStatus.PENDING:
            comment = f"[管理员越级直批] {comment or ''}".strip()
        expense.status = (
            ExpenseStatus.MANAGER_APPROVED if is_first_review else ExpenseStatus.APPROVED
        )
        if expense.status == ExpenseStatus.APPROVED:
            expense.approved_at = utc_now()
        expense.rejection_reason = None
        action = ApprovalAction.APPROVE
    else:
        step = "manager" if expense.status == ExpenseStatus.PENDING else "finance"
        expense.status = ExpenseStatus.REJECTED
        expense.rejection_reason = req.comment or "审批驳回（未填写原因）"
        action = ApprovalAction.REJECT

    db.add(Approval(
        expense_id=expense.id,
        approver_id=user.id,
        approver_name=user.full_name or user.username,
        action=action,
        comment=comment,
        step=step,
    ))
    db.commit()
    db.refresh(expense)
    # 通知申请人（站内信必有、邮件尽力而为；任何失败不影响审批结果）
    try:
        notify_human_decision(
            db, expense,
            approved=req.action == "approve",
            reason=req.comment, step=step,
        )
    except Exception as e:
        logger.warning(f"审批结果通知失败（不影响主流程）: {e}")
    logger.info(f"{user.username} {req.action}({step}) 报销单 {expense.expense_no}")
    return expense
```

- [ ] **Step 4: 运行（通知签名未改，先预期2个FAIL）**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_api/test_approvals.py -v`
Expected: decide 调 `notify_human_decision(..., step=...)` TypeError → 决策类用例 FAIL。属预期：Task 3 改签名后转绿。

- [ ] **Step 5: 提交（与 Task 3 合并提交）**

（本任务代码与通知签名改动互相依赖，合并到 Task 3 末尾统一提交。）

---

### Task 3: 通知文案分初审/终审 + workflow 跳过规则

**Files:**
- Modify: `backend/app/services/notification_service.py`
- Modify: `backend/app/agents/workflow.py`
- Test: `backend/tests/test_agents/test_workflow_skip.py`

- [ ] **Step 1: 写失败测试**

```python
"""
workflow manual_review 落库分流测试：
部门有在职经理→PENDING；申请人本人是经理/部门无经理→直接MANAGER_APPROVED(留痕)
"""
import asyncio

from app.agents import workflow as wf
from app.models import Expense, ExpenseStatus

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "跳过初审测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-SKIP-001",
        }
    ],
}


class _FakeGraph:
    """固定 manual_review 裁决"""
    async def ainvoke(self, state, config=None):
        return {
            "risk": {"risk_score": 60.0, "risk_level": "medium", "factors": []},
            "decision": {"action": "manual_review", "reason": "中风险", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {"invoice_verified": True, "anomalies": [], "summary": "",
                         "ocr_items": {}},
            "errors": [],
        }


def _setup(monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )


@requires_db
def test_lands_pending_when_manager_exists(client, db_session, monkeypatch):
    """部门有在职经理（测试部）→PENDING"""
    _setup(monkeypatch)
    register_and_login(client, "sk_mgr0", role="manager")  # 测试部在职经理
    headers = register_and_login(client, "sk_e1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    asyncio.run(wf.workflow.run(db_session, expense_id))
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.PENDING


@requires_db
def test_skips_when_no_manager_in_department(client, db_session, monkeypatch):
    """部门无在职经理→直接MANAGER_APPROVED，且留痕Approval(step=manager)"""
    _setup(monkeypatch)
    headers = register_and_login(client, "sk_e2")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    asyncio.run(wf.workflow.run(db_session, expense_id))
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.MANAGER_APPROVED
    rec = [a for a in expense.approvals if a.step == "manager"]
    assert rec and "跳过" in (rec[0].comment or "")


@requires_db
def test_skips_when_applicant_is_manager(client, db_session, monkeypatch):
    """申请人本人是经理（不能自审）→直接MANAGER_APPROVED"""
    _setup(monkeypatch)
    headers = register_and_login(client, "sk_mgr3", role="manager")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    asyncio.run(wf.workflow.run(db_session, expense_id))
    expense = db_session.get(Expense, expense_id)
    db_session.refresh(expense)
    assert expense.status == ExpenseStatus.MANAGER_APPROVED
```

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_agents/test_workflow_skip.py -v`
Expected: 3 FAIL（现在一律落 PENDING）

- [ ] **Step 3: 实现**

`backend/app/services/notification_service.py` —— `notify_human_decision` 整体替换：

```python
def notify_human_decision(db: Session, expense: Expense, approved: bool,
                          reason: str | None, step: str | None = None) -> None:
    """人工审批结果通知申请人（step区分初审/终审文案）"""
    no = expense.expense_no
    if approved:
        if step == "manager":
            title, content = "报销单已通过经理初审", f"您的报销单 {no} 已通过经理初审，等待财务终审。"
        else:
            title, content = "报销单已通过财务终审", f"您的报销单 {no} 已完成全部审批，等待财务打款。"
    else:
        stage = "经理初审" if step == "manager" else "财务终审"
        title, content = "报销单被驳回", f"您的报销单 {no} 在{stage}环节被驳回。\n原因：{reason or '未填写'}"
    send_notification(db, expense.user_id, title, content, "approval")
```

`backend/app/agents/workflow.py`：
1) 顶部 import 补 `UserRole`（从 app.models，与现有 Expense 等同处 import 行合并）。
2) 模块级（class 外）加辅助函数：

```python
def _should_skip_manager_review(db, expense) -> tuple[bool, str]:
    """确定性跳过经理初审判定：申请人本人是经理 / 部门无在职经理"""
    owner = expense.user
    if owner is None:
        return False, ""
    if owner.role == UserRole.MANAGER:
        return True, "申请人本人为经理，不能自审"
    if owner.department:
        from app.models import User
        has_manager = (
            db.query(User)
            .filter(
                User.role == UserRole.MANAGER,
                User.is_active.is_(True),
                User.department == owner.department,
            )
            .first()
            is not None
        )
        if not has_manager:
            return True, f"部门「{owner.department}」无在职经理"
    return False, ""
```

3) `run()` 第 4 步 else 分支替换为：

```python
        else:
            # 转人工：按确定性规则决定是否跳过经理初审
            skip, skip_reason = _should_skip_manager_review(db, expense)
            if skip:
                expense.status = ExpenseStatus.MANAGER_APPROVED
                db.add(Approval(
                    expense_id=expense_id,
                    approver_id=None,
                    approver_name="系统（自动跳过初审）",
                    action=ApprovalAction.APPROVE,
                    comment=f"自动跳过经理初审：{skip_reason}",
                    step="manager",
                ))
            else:
                expense.status = ExpenseStatus.PENDING
```

- [ ] **Step 4: 运行确认通过（含 Task 2 全量）**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_agents/ tests/test_api/test_approvals.py tests/test_api/test_expenses.py -v`
Expected: 全部 passed

- [ ] **Step 5: 提交（含 Task 2 文件）**

```bash
git add backend/app/services backend/app/agents/workflow.py backend/app/schemas/approval.py backend/tests
git commit -m "feat(approval): 两级审批链——decide规则表+初审跳过+通知分阶段文案" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 前端——审批中心分组 + 状态/时间线适配

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/constants/index.ts`
- Modify: `frontend/src/views/ApprovalCenterView.vue`
- Modify: `frontend/src/components/ExpenseDetailDrawer.vue`

- [ ] **Step 1: types + constants**

`frontend/src/types/index.ts`：ExpenseStatus 联合类型 `pending` 后加一行：

```typescript
export type ExpenseStatus =
  | 'draft'
  | 'submitted'
  | 'pending'
  | 'manager_approved'
  | 'approved'
  | 'rejected'
  | 'paid'
  | 'cancelled'
```

ApprovalRecord 接口 `ai_decision` 行后加：

```typescript
  ai_decision: string | null
  step: 'manager' | 'finance' | null
```

PendingExpense 接口 `id` 行后加：

```typescript
  id: number
  status: ExpenseStatus
```

`frontend/src/constants/index.ts` STATUS_MAP `pending` 行后加：

```typescript
  pending: { label: '待审批', type: 'warning' },
  manager_approved: { label: '待财务终审', type: 'primary' },
```

- [ ] **Step 2: ApprovalCenterView 分组**

`<script setup>` 改动（import 区加、state 加、模板换表）：

```typescript
import { useUserStore } from '@/stores/user'
```

```typescript
const userStore = useUserStore()
const role = computed(() => userStore.user?.role || 'employee')
// 初审按钮：manager/admin；终审按钮：finance/admin
const canDecide = (status: string) =>
  status === 'pending'
    ? ['manager', 'admin'].includes(role.value)
    : ['finance', 'admin'].includes(role.value)
const pendingItems = computed(() => items.value.filter((i) => i.status === 'pending'))
const finalItems = computed(() => items.value.filter((i) => i.status === 'manager_approved'))
```

（`computed` 需已 import，若无则并入 vue import 行。）

模板：原 `<el-table :data="items" stripe>` 整块包进 el-tabs，两块表结构相同仅数据源/按钮显隐不同：

```vue
      <el-tabs model-value="first">
        <el-tab-pane label="待经理初审" name="first">
          <el-table v-loading="loading" :data="pendingItems" stripe>
            <!-- 原全部列照搬 -->
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <template v-if="canDecide('pending')">
                  <el-button link type="success" @click="openDecide(row, 'approve')">通过</el-button>
                  <el-button link type="danger" @click="openDecide(row, 'reject')">驳回</el-button>
                </template>
                <span v-else style="color: #c0c4cc; font-size: 12px">等待经理初审</span>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无待初审单据" :image-size="80" />
            </template>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="待财务终审" name="final">
          <el-table v-loading="loading" :data="finalItems" stripe>
            <!-- 同上，列照搬；操作列 canDecide('manager_approved')，占位文案「等待财务终审」 -->
          </el-table>
        </el-tab-pane>
      </el-tabs>
```

（写实现时两个 tab 的列定义完整复制，不改列结构；对话框标题按 action 不变。顶部 el-alert 说明文案改为：「两级审批：经理初审（本部门）→ 财务终审。此处为 AI 转人工的单据；无经理的部门已自动跳过初审。」）

- [ ] **Step 3: ExpenseDetailDrawer 时间线 step 渲染**

`actionLabel` 函数替换（按 action+step 组合）：

```typescript
function actionLabel(action: string, step?: 'manager' | 'finance' | null): string {
  if (action === 'approve') {
    if (step === 'manager') return '初审通过（经理）'
    if (step === 'finance') return '终审通过（财务）'
    return '审批通过'
  }
  if (action === 'reject') {
    if (step === 'manager') return '初审驳回（经理）'
    if (step === 'finance') return '终审驳回（财务）'
    return '审批驳回'
  }
  const map: Record<string, string> = { submit: '提交报销', ai_review: 'AI 审核' }
  return map[action] || action
}
```

模板调用处改为 `actionLabel(record.action, record.step)`。

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/constants/index.ts frontend/src/views/ApprovalCenterView.vue frontend/src/components/ExpenseDetailDrawer.vue
git commit -m "feat(frontend): 审批中心分待初审/待终审+时间线按层级渲染" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 收尾——全量回归 + README

- [ ] **Step 1: 后端全量**

Run: `cd backend && TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest tests/ -q`
Expected: 全部 passed（约 100），2 deselected

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: README.md 107 行改 ✅**

```
| 🔗 Multi-level approval | ✅ Done | Fixed two-level chain: manager first review (own department) → finance final approval; new `manager_approved` status, `approvals.step` audit trail, approval center split into first/final queues, admin override, auto-skip when no manager in department |
```

- [ ] **Step 4: README.zh-CN.md 107 行改 ✅**

```
| 🔗 多级审批流 | ✅ 已完成 | 固定两级链：经理初审（本部门）→ 财务终审；新增 `manager_approved` 状态、`approvals.step` 层级留痕、审批中心分待初审/待终审、admin 越级直批兜底、无经理部门自动跳过初审 |
```

- [ ] **Step 5: 提交**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: 阶段③完成——两级审批链从WIP表移除" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 验收（对照规格阶段③）

1. 完整链实测：转人工 → 经理初审通过（manager_approved, step=manager）→ 财务终审通过（approved + approved_at, step=finance）；任一级驳回 → rejected 带原因
2. finance 不可操作 PENDING（400 提示先初审）；admin 可从 PENDING 越级直批 APPROVED（留痕「管理员越级直批」）；manager 不可终审
3. 跳过规则：申请人=经理 或 部门无在职经理 → 落库直接 MANAGER_APPROVED + 系统 Approval 留痕
4. list_pending：manager 只见本部门 PENDING；finance/admin 见两级队列；返回项带 status
5. 时间线渲染「初审通过（经理）/ 终审通过（财务）」；通知文案区分初审/终审
6. `uv run pytest`（约 100 用例）与 `npm run build` 全绿；迁移脚本对 dev/test 库各执行一次成功且幂等
