# AI Agent 财务报销审核系统

[English](README.md) | **简体中文**

基于 **LangGraph 多 Agent 协同 + RAG + 规则引擎** 的智能财务报销审核系统。
让 AI 处理大部分明确无误的单据（自动通过/驳回），把人工精力集中在真正需要判断的单据上；**关键裁决（放行/驳回）永远由确定性代码执行，LLM 只提供建议**。

## 核心特性

- 🔐 **认证与权限**：JWT 登录，4 种角色（admin / finance / manager / employee），数据可见范围按角色隔离
- 📄 **报销管理**：报销单（含多明细）增删改查、提交、取消；金额自动汇总；草稿/被驳回可编辑重提
- 🤖 **AI 审核工作流**：提交后自动触发，LangGraph 编排 5 个 Agent（单据解析 → 规则校验 ∥ RAG 检索 → 风险评估 → 终审裁决）
  - `auto_approve` 低风险自动通过 / `auto_reject` 硬性违规自动驳回 / `manual_review` 转人工
  - 风险分 = max(LLM 评分, 规则引擎确定性计分)，等级阈值由代码判定
- 📚 **RAG 知识库**：ChromaDB 向量库 + GLM embedding，检索「公司制度」与「历史相似案例」；每次审核自动回填案例（数据飞轮）
- ✅ **人工审批中心**：manager 限本部门、finance/admin 审全部，审批历史与 AI 审核共用同一时间线
- 💰 **财务打款登记**：approved → paid，真实转账在系统外完成
- 📏 **规则管理**：可视化维护审核规则（金额/发票/日期/重复发票），三级严重度 BLOCK / REVIEW / WARN
- 📊 **报表统计**：总览、月度趋势、分类占比（Redis 缓存，可选）

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 · MySQL（可切 PostgreSQL）· Redis（可选） |
| AI | LangGraph · LangChain · GLM（glm-5.1 对话 + embedding-3 向量）· ChromaDB |
| 前端 | Vue 3 · TypeScript · Vite · Element Plus · Pinia · vue-router |
| 工程 | uv（依赖管理）· pytest · docker-compose（本地 PostgreSQL/Redis 辅助服务） |

## AI 审核工作流

```
提交报销单（后台异步执行，接口立即返回）
        ↓
┌─ ① DB预加载：单据快照 + 规则 + 重复发票检查 ─┐
│  ② LangGraph 图执行                          │
│                                              │
│  单据解析Agent ──┬→ 规则校验Agent（纯代码引擎）│
│                 └→ RAG检索Agent   （两路并行）│
│                        ↓ fan-in              │
│                  风险评估Agent（0-100分）      │
│                        ↓                     │
│                  决策Agent（代码终审）         │
├─ ③④ 结果落库：AI字段 + 状态流转 + 审批流水 ──┤
└─ ⑤ 案例回填知识库（未来相似案例检索）─────────┘
```

## 快速开始

### 1. 后端

```bash
# 依赖安装（项目根目录）
uv sync

# 配置环境变量：复制 backend/.env.example 为根目录 .env 并填写
# 必填：DATABASE_URL / GLM_API_KEY / JWT_SECRET_KEY / SECRET_KEY

# 初始化数据库（建表 + 4演示账号/6费用类别/8审核规则）
cd backend
uv run python scripts/init_db.py

# 初始化RAG知识库（灌入示例财务制度，需GLM_API_KEY）
uv run python scripts/init_knowledge.py

# 启动（务必在 backend/ 目录下，数据目录相对CWD落盘）
uv run uvicorn app.main:app --reload --port 8000
```

启动后访问 Swagger 文档：<http://localhost:8000/api/docs>

### 2. 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173（/api 已代理到 8000）
```

### 3. 演示账号（init_db.py 创建）

| 账号 | 密码 | 角色 | 权限 |
|---|---|---|---|
| admin | admin123 | 管理员 | 全部权限（用户/规则管理） |
| finance01 | finance123 | 财务 | 审批全部单据、报表、打款登记 |
| manager01 | manager123 | 部门经理 | 审批本部门单据 |
| employee01 | employee123 | 普通员工 | 提交报销、查看本人单据 |

### 4. 测试

```bash
uv run pytest -v                # 常规测试（规则引擎单测无需外部依赖；DB不可达自动跳过API用例）
uv run pytest -m llm -v         # LLM 真实联调用例（需 GLM_API_KEY + 测试库）
```

## 暂未完成的业务

以下功能尚未实现或只有半成品，欢迎按此清单补全：

| 事项 | 现状 | 待完成内容 |
|---|---|---|
| 📎 发票文件上传 | ✅ 已完成 | `POST /api/uploads`（pdf/jpg/jpeg/png/docx，≤10MB）→ 落盘 `/uploads/yyyy/mm/`，静态文件服务 |
| 🔍 真实 OCR | ✅ 已完成 | 混合流水线：RapidOCR → 正则KIE（置信度≥0.85且关键字段齐全）或 GLM-VLM 兜底 → 确定性业务校验（税号18/20位、不含税+税额=价税合计±0.01）；txt/docx 直读 |
| 📧 审核结果通知 | ✅ 已完成 | 站内信铃铛（30秒轮询）+ 邮件尽力而为；AI审核/人工审批/打款登记三个触发点 |
| 📤 报表导出 | ✅ 已完成 | `GET /api/reports/export` 返回4-sheet xlsx（总览/趋势/分类/明细）；finance/admin |
| 👥 用户管理页面 | ✅ 已完成 | `/users` admin页面：改角色/启停，禁止操作自己 |
| 🔗 多级审批流 | ❌ 未设计 | 当前为单人终审（manager 或 finance 一次决策），无「经理 → 财务」多级审批链 |
| 🐳 容器化部署 | ⚠️ 半成品 | docker-compose 仅含 PostgreSQL/Redis 辅助服务；backend/frontend 无 Dockerfile，无 nginx 反向代理配置 |
| 🧪 测试覆盖 | ⚠️ 部分 | users / rules / categories / reports / agent 接口无用例；AI 工作流用例需 `-m llm` 真实调用大模型 |
