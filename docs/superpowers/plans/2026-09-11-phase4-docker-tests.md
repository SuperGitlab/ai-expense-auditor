# 阶段④ 实施计划：容器化部署 + 测试收尾

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地规格 [2026-09-09-unfinished-features-design.md](../specs/2026-09-09-unfinished-features-design.md) 的阶段④——`docker compose up` 一条命令起全栈（db/redis/backend/frontend/init），并补齐存量测试欠账（rules/categories/agent + users/reports 缺口）。

**Architecture:** 前后端各一个生产镜像（backend: python:3.12-slim + uv sync；frontend: node 构建 → nginx 托管），compose 编排五个服务（含一次性 init 建库种子、`--profile knowledge` 可选知识库初始化）。**关键约束：pyproject.toml/uv.lock 在仓库根而非 backend/**，故 backend 镜像构建上下文必须是仓库根（`dockerfile: backend/Dockerfile`），容器内复刻 `/app/{pyproject.toml,uv.lock,backend/}` 布局、WORKDIR `/app/backend`，使 `./uploads ./data ./logs ./data/chroma` 相对路径与开发环境一致。测试补齐沿用 conftest 模式（DB 不可达自动跳过）。

**Tech Stack:** Docker multi-stage · uv · nginx · pytest

**重要约束:**
- 后端测试命令（在 `backend/` 目录执行）：
  `TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest <路径> -v`
- compose 默认 PostgreSQL（`psycopg2-binary` 已在依赖）；README 注明切 MySQL 仅改 DATABASE_URL
- 新库走 `scripts/init_db.py` 建表（全量新结构），**不需要** migrate_v2.py（它仅用于 MySQL 存量库）
- `AGENT_REVIEW_ON_SUBMIT=False` 时 submit 不触发 AI；测试直改状态模拟

---

## 文件结构

| 动作 | 文件 | 职责 |
|---|---|---|
| Create | `backend/Dockerfile` | 后端镜像（构建上下文=仓库根） |
| Create | `frontend/Dockerfile` | 前端两阶段镜像 |
| Create | `frontend/nginx.conf` | SPA 路由 + /api、/uploads 反代 |
| Create | `.dockerignore`（根） | 排除 .git/.env/node_modules/运行数据 |
| Create | `frontend/.dockerignore` | 前端构建上下文瘦身 |
| Modify | `docker-compose.yml` | 加 backend/frontend/init/knowledge 服务 |
| Create | `.env.docker.example` | 容器环境变量模板 |
| Test | `backend/tests/test_api/test_rules.py` | 规则 CRUD、admin 鉴权、active_only |
| Test | `backend/tests/test_api/test_categories.py` | 类别列表 |
| Test | `backend/tests/test_api/test_agent.py` | workflow 信息接口、review 权限/状态门槛 |
| Modify | `backend/tests/test_api/test_users.py` | +筛选、+启停 |
| Modify | `backend/tests/test_api/test_reports.py` | +by-category 接口 |
| Modify | `README.md` / `README.zh-CN.md` | 108/109 行改 ✅ |

---

### Task 0: 前置准备

- [ ] **Step 1: 创建功能分支**

```bash
git checkout -b feat/phase4-docker-tests
```

---

### Task 1: 后端镜像 + 根 .dockerignore

**Files:**
- Create: `backend/Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: 写 `backend/Dockerfile`**

```dockerfile
# 后端生产镜像
# 注意：构建上下文是仓库根（pyproject.toml/uv.lock 在根），见 compose 的 build.context
FROM python:3.12-slim

# libgomp1: onnxruntime(rapidocr)运行依赖；tini: 容器信号转发
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# 先拷依赖清单再拷代码（利用层缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./backend/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
# ./uploads ./data ./logs 相对路径基于此目录，与开发环境一致
RUN mkdir -p uploads data logs

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 写根 `.dockerignore`**（backend 镜像构建上下文瘦身）

```
.git
.env
*.md
docs/
my_self/
logs/
frontend/
# 后端运行数据不进镜像（挂卷）
backend/uploads/
backend/data/
backend/logs/
backend/.venv/
**/__pycache__/
**/*.pyc
.pytest_cache/
```

- [ ] **Step 3: 构建验证**

Run: `cd /d/gk/financial_reimbursement_review && docker build -f backend/Dockerfile -t expense-backend:dev . && echo BUILD-OK`
Expected: `BUILD-OK`（若 Docker 未运行则记录跳过，Task 4 统一处理）

- [ ] **Step 4: 提交**

```bash
git add backend/Dockerfile .dockerignore
git commit -m "feat(docker): 后端生产镜像(uv+slim)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 前端镜像 + nginx

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: 写 `frontend/Dockerfile`**

```dockerfile
# 前端两阶段镜像：node构建 → nginx托管
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 2: 写 `frontend/nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;

    # 上传接口限额对齐后端 MAX_FILE_SIZE(10MB)，nginx默认1m会挡上传
    client_max_body_size 15m;

    # SPA history 路由
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端API与发票文件静态服务反代
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /uploads/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }
}
```

- [ ] **Step 3: 写 `frontend/.dockerignore`**

```
node_modules
dist
.dockerignore
Dockerfile
```

- [ ] **Step 4: 构建验证**

Run: `cd /d/gk/financial_reimbursement_review/frontend && docker build -t expense-frontend:dev . && echo BUILD-OK`
Expected: `BUILD-OK`（Docker 未运行则记录跳过）

- [ ] **Step 5: 提交**

```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore
git commit -m "feat(docker): 前端两阶段镜像+nginx反代" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: compose 编排 + 环境模板

**Files:**
- Modify: `docker-compose.yml`（保留现有 db/redis，追加服务）
- Create: `.env.docker.example`

- [ ] **Step 1: 追加服务到 `docker-compose.yml`**

在 `redis:` 服务块之后、`volumes:` 之前追加：

```yaml
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: expense_backend
    environment:
      DATABASE_URL: ${DOCKER_DATABASE_URL:-postgresql+psycopg2://user:password@db:5432/expense_db}
      REDIS_URL: redis://redis:6379/0
      APP_ENV: production
      DEBUG: "False"
      SECRET_KEY: ${SECRET_KEY:-change-me-in-env}
      JWT_SECRET_KEY: ${SECRET_KEY:-change-me-in-env}
      GLM_API_KEY: ${GLM_API_KEY:-}
      GLM_API_BASE: ${GLM_API_BASE:-https://open.bigmodel.cn/api/paas/v4}
      MODEL_NAME: ${MODEL_NAME:-glm-5.1}
      ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost}
      OCR_PROVIDER: ${OCR_PROVIDER:-hybrid}
    ports:
      - "8000:8000"
    volumes:
      - uploads:/app/backend/uploads
      - appdata:/app/backend/data
      - applogs:/app/backend/logs
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
    container_name: expense_frontend
    ports:
      - "80:80"
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped

  # 一次性建表+种子账户（新库全量结构，无需migrate_v2）
  init:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: expense_init
    environment:
      DATABASE_URL: ${DOCKER_DATABASE_URL:-postgresql+psycopg2://user:password@db:5432/expense_db}
      REDIS_URL: redis://redis:6379/0
      GLM_API_KEY: ${GLM_API_KEY:-}
    command: ["python", "scripts/init_db.py"]
    depends_on:
      db:
        condition: service_healthy
    restart: "no"

  # 可选：知识库初始化（需GLM key） docker compose --profile knowledge up
  knowledge-init:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: expense_knowledge_init
    environment:
      DATABASE_URL: ${DOCKER_DATABASE_URL:-postgresql+psycopg2://user:password@db:5432/expense_db}
      REDIS_URL: redis://redis:6379/0
      GLM_API_KEY: ${GLM_API_KEY:-}
      GLM_API_BASE: ${GLM_API_BASE:-https://open.bigmodel.cn/api/paas/v4}
      MODEL_NAME: ${MODEL_NAME:-glm-5.1}
      EMBEDDING_MODEL_NAME: ${EMBEDDING_MODEL_NAME:-embedding-3}
    command: ["python", "scripts/init_knowledge.py"]
    depends_on:
      db:
        condition: service_healthy
    profiles: ["knowledge"]
    restart: "no"
```

并把 `volumes:` 段扩为：

```yaml
volumes:
  pgdata:
  redisdata:
  uploads:
  appdata:
  applogs:
```

- [ ] **Step 2: 写 `.env.docker.example`**

```
# ============================================
# Docker部署环境变量模板
# 复制为项目根目录 .env.docker 后：docker compose --env-file .env.docker up -d --build
# （不复制也可直接up，全部走内置默认值，适合本地体验）
# ============================================

# 数据库连接（容器网络内主机名=db；默认PostgreSQL，切MySQL示例见下）
# DOCKER_DATABASE_URL=postgresql+psycopg2://user:password@db:5432/expense_db
# DOCKER_DATABASE_URL=mysql+pymysql://user:password@db:3306/expense_db?charset=utf8mb4

# JWT/会话密钥（生产必改）
SECRET_KEY=change-me-to-a-random-string

# GLM 智谱（AI审核/OCR需要；不填则LLM相关功能降级）
GLM_API_KEY=
# GLM_API_BASE=https://open.bigmodel.cn/api/paas/v4
# MODEL_NAME=glm-5.1
# EMBEDDING_MODEL_NAME=embedding-3

# OCR：off=关闭混合流水线（无key环境保持占位行为）
# OCR_PROVIDER=hybrid

# CORS（前端访问入口）
# ALLOWED_ORIGINS=http://localhost
```

- [ ] **Step 3: 语法校验**

Run: `cd /d/gk/financial_reimbursement_review && docker compose config -q && echo COMPOSE-OK`
Expected: `COMPOSE-OK`（Docker 未运行则 `docker compose version` 至少验证 CLI 存在并记录）

- [ ] **Step 4: 提交**

```bash
git add docker-compose.yml .env.docker.example
git commit -m "feat(docker): compose全栈编排(db/redis/backend/frontend/init)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 容器冒烟（尽力而为）

- [ ] **Step 1: 若 Docker 可用，起全栈冒烟**

```bash
docker compose up -d --build && sleep 45
curl -s http://localhost:8000/health && curl -s -o /dev/null -w "%{http_code}" http://localhost/ && echo FRONTEND-OK
docker compose ps
docker compose down
```
Expected: health 返回 JSON、前端 200、全部服务 healthy/exit 0

（若本机 Docker Desktop 未运行/未安装：跳过本任务，在最终汇报中注明「构建与编排已就绪，全栈启动由用户执行验收」——不阻塞后续测试任务。）

---

### Task 5: test_rules.py（规则 CRUD + 鉴权）

**Files:**
- Test: `backend/tests/test_api/test_rules.py`

- [ ] **Step 1: 写测试（新文件）**

```python
"""
规则接口测试（需测试DB）：CRUD全流程 + admin鉴权 + active_only过滤
"""
from tests.conftest import register_and_login, requires_db

RULE_PAYLOAD = {
    "name": "测试餐费限额",
    "code": "test_meal_limit",
    "rule_type": "amount_limit",
    "field_name": "amount",
    "operator": "gt",
    "threshold": "500",
    "severity": "warn",
    "risk_points": 20,
    "description": "单条餐费超500元警示",
}


@requires_db
def test_rules_require_auth(client):
    """未登录401"""
    assert client.get("/api/rules").status_code == 401


@requires_db
def test_rules_write_requires_admin(client):
    """非admin建规则403（登录可读列表）"""
    headers = register_and_login(client, "rl_fin", role="finance")
    assert client.get("/api/rules", headers=headers).status_code == 200
    assert client.post("/api/rules", json=RULE_PAYLOAD, headers=headers).status_code == 403


@requires_db
def test_rule_crud_flow(client, db_session):
    """admin：建→读→改→停用→active_only过滤→删"""
    admin_headers = register_and_login(client, "rl_adm", role="admin")

    resp = client.post("/api/rules", json=RULE_PAYLOAD, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    rule_id = resp.json()["id"]
    assert resp.json()["is_active"] is True

    resp = client.put(
        f"/api/rules/{rule_id}",
        json={"threshold": "800", "severity": "review"},
        headers=admin_headers,
    )
    assert resp.status_code == 200 and resp.json()["threshold"] == "800"

    # 停用后 active_only 不再返回
    client.put(f"/api/rules/{rule_id}", json={"is_active": False}, headers=admin_headers)
    all_ids = [r["id"] for r in client.get("/api/rules", headers=admin_headers).json()]
    active_ids = [
        r["id"] for r in client.get("/api/rules?active_only=true", headers=admin_headers).json()
    ]
    assert rule_id in all_ids and rule_id not in active_ids

    assert client.delete(f"/api/rules/{rule_id}", headers=admin_headers).status_code == 204
    assert client.delete(f"/api/rules/{rule_id}", headers=admin_headers).status_code == 404
```

- [ ] **Step 2: 运行**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_api/test_rules.py -v`（前缀同上）
Expected: 3 passed（接口已有实现，此为存量补测——若失败说明实现有 bug，按红灯修）

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_api/test_rules.py
git commit -m "test: 规则接口CRUD与鉴权用例" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: test_categories.py + test_agent.py

**Files:**
- Test: `backend/tests/test_api/test_categories.py`
- Test: `backend/tests/test_api/test_agent.py`

- [ ] **Step 1: 写 `test_categories.py`**

```python
"""
类别接口测试（需测试DB）：登录可读、含种子类别、未登录401
"""
from tests.conftest import register_and_login, requires_db


@requires_db
def test_categories_require_auth(client):
    assert client.get("/api/categories").status_code == 401


@requires_db
def test_categories_list_contains_seeds(client):
    """种子数据含差旅费/餐饮费（conftest种子id 1/2）"""
    headers = register_and_login(client, "cat_e1")
    resp = client.get("/api/categories", headers=headers)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "差旅费" in names and "餐饮费" in names
```

- [ ] **Step 2: 写 `test_agent.py`**

```python
"""
AI审核接口测试（需测试DB）：workflow信息接口 + review权限/状态门槛（monkeypatch掉真工作流）
"""
from app.api.endpoints import agent as agent_module

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "agent接口测试",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "60.00",
            "expense_date": "2026-09-02",
            "invoice_no": "INV-AGENT-001",
        }
    ],
}


def _create_draft(client, username):
    headers = register_and_login(client, username)
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    return resp.json()["id"], headers


@requires_db
def test_workflow_info(client):
    """工作流结构接口：登录即可读，返回nodes/edges"""
    headers = register_and_login(client, "ag_e1")
    resp = client.get("/api/agent/workflow", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "decision" in body["nodes"]
    assert any(e["to"] == "END" for e in body["edges"])


@requires_db
def test_review_cannot_touch_others_expense(client, db_session):
    """employee不能触发他人单据→403"""
    headers_owner = register_and_login(client, "ag_owner")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers_owner)
    other_id = resp.json()["id"]
    other_headers = register_and_login(client, "ag_e3")
    resp = client.post(
        "/api/agent/review", json={"expense_id": other_id}, headers=other_headers
    )
    assert resp.status_code == 403


@requires_db
def test_review_status_gate(client, db_session):
    """DRAFT状态不可触发审核→400（权限先过：admin触发他人草稿）"""
    expense_id, _ = _create_draft(client, "ag_e4")
    admin_headers = register_and_login(client, "ag_adm4", role="admin")
    resp = client.post(
        "/api/agent/review", json={"expense_id": expense_id}, headers=admin_headers
    )
    assert resp.status_code == 400
    assert "不可审核" in resp.json()["detail"]


@requires_db
def test_review_success_with_fake_workflow(client, db_session, monkeypatch):
    """SUBMITTED状态+本人触发：monkeypatch工作流返回固定结果→200"""
    expense_id, headers = _create_draft(client, "ag_e5")
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    async def _fake_run(db, expense_id):
        return {
            "expense_id": expense_id, "risk_level": "low", "risk_score": 20.0,
            "decision": "auto_approve", "review_result": "{}", "suggestions": [],
            "relevant_rules": [], "similar_cases": [], "rule_violations": [],
            "workflow_errors": [], "elapsed_seconds": 0.1,
        }

    monkeypatch.setattr(agent_module, "workflow",
                        type("W", (), {"run": staticmethod(_fake_run)})())
    resp = client.post(
        "/api/agent/review", json={"expense_id": expense_id}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "auto_approve"
```

- [ ] **Step 3: 运行**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_api/test_categories.py tests/test_api/test_agent.py -v`
Expected: 6 passed

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_api/test_categories.py backend/tests/test_api/test_agent.py
git commit -m "test: 类别与AI审核接口用例" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: test_users 补筛选/启停 + test_reports 补 by-category

**Files:**
- Modify: `backend/tests/test_api/test_users.py`（追加用例）
- Modify: `backend/tests/test_api/test_reports.py`（追加用例）

- [ ] **Step 1: test_users.py 末尾追加**

```python
@requires_db
def test_list_filter_by_role(client):
    """admin按角色筛选用户列表"""
    admin_headers = register_and_login(client, "ul_adm", role="admin")
    register_and_login(client, "ul_fin", role="finance")
    register_and_login(client, "ul_emp")
    body = client.get("/api/users?role=finance", headers=admin_headers).json()
    assert body and all(u["role"] == "finance" for u in body)
    assert any(u["username"] == "ul_fin" for u in body)
    assert all(u["username"] != "ul_emp" for u in body)


@requires_db
def test_toggle_user_status(client):
    """admin启停另一用户；不能停用自己"""
    admin_headers = register_and_login(client, "us_adm", role="admin")
    register_and_login(client, "us_emp")
    body = client.get("/api/users", headers=admin_headers).json()
    emp_id = next(u["id"] for u in body if u["username"] == "us_emp")
    resp = client.patch(
        f"/api/users/{emp_id}/status", json={"is_active": False}, headers=admin_headers
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    # 不能停用自己
    my_id = next(u["id"] for u in body if u["username"] == "us_adm")
    resp = client.patch(
        f"/api/users/{my_id}/status", json={"is_active": False}, headers=admin_headers
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: test_reports.py 末尾追加**

```python
@requires_db
def test_by_category(client, db_session):
    """分类统计接口返回类别金额聚合"""
    finance_headers = register_and_login(client, "rp_fin3", role="finance")
    headers = register_and_login(client, "rp_e3")
    resp = client.post("/api/expenses", json=EXPENSE_PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
    resp = client.get("/api/reports/by-category", headers=finance_headers)
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    # 新建单据已计入某类别
    assert sum(i["count"] for i in items) >= 1
```

（`EXPENSE_PAYLOAD` 若与现有文件重名冲突——现有 test_reports.py 若已定义同名单据载荷则直接复用；实现时以文件现状为准调整变量名。）

- [ ] **Step 3: 运行**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_api/test_users.py tests/test_api/test_reports.py -v`
Expected: 全部 passed

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_api/test_users.py backend/tests/test_api/test_reports.py
git commit -m "test: 用户筛选启停与分类统计用例" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: 全量回归 + README 收尾

- [ ] **Step 1: 后端全量**

Run: `cd backend && TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest tests/ -q`
Expected: 全部 passed（约 112），2 deselected

- [ ] **Step 2: README WIP 表容器化/测试两行改 ✅**（EN/zh 各自的容器化与测试行；EN 示例）

```
| 🐳 Docker deployment | ✅ Done | `docker compose up -d --build` starts the full stack (PostgreSQL/Redis/backend/nginx-frontend + one-shot init); volumes persist uploads/Chroma/logs; see `.env.docker.example` |
```

```
| 🧪 Test coverage | ✅ Done | ~112 pytest cases: auth/expenses/approval chain/notifications/uploads/OCR pipeline/users/rules/categories/reports/agent; DB-gated tests auto-skip when unreachable |
```

（zh 对应翻译；执行时以两文件实际行内容替换 ❌ 行。）

- [ ] **Step 3: 提交**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: 阶段④完成——容器化与测试从WIP表移除" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 验收（对照规格阶段④）

1. `docker build` 两镜像成功；`docker compose config` 语法通过（全栈 up 由用户环境验收）
2. compose 五服务：db/redis(healthy) → backend(healthcheck过/health) → frontend(80) + init(建表种子跑完退出)；`--profile knowledge` 可选
3. uploads/data(chroma)/logs 全落卷；PG 为默认库，README 注明切 MySQL 仅改 DATABASE_URL
4. pytest 覆盖 rules/categories/agent/users 筛选启停/reports by-category，全绿
5. README 8 项全部 ✅
