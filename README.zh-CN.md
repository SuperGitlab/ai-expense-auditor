# AI Agent 财务报销审核系统

[English](README.md) | **简体中文**

基于 **LangGraph 多 Agent 协同 + RAG + 规则引擎** 的智能财务报销审核系统。
让 AI 处理大部分明确无误的单据（自动通过/驳回），把人工精力集中在真正需要判断的单据上；**关键裁决（放行/驳回）永远由确定性代码执行，LLM 只提供建议**。

## 核心特性

- 🔐 **认证与权限**：JWT 登录，4 种角色（admin / finance / manager / employee），数据可见范围按角色隔离
- 📄 **报销管理**：报销单（含多明细）增删改查、提交、取消；金额自动汇总；报销类型未手动选择时按明细费用类别自动带出；草稿/被驳回可编辑重提
- 🤖 **AI 审核工作流**：提交后自动触发，LangGraph 编排 5 个 Agent（单据解析 → 规则校验 ∥ RAG 检索 → 风险评估 → 终审裁决）
  - `auto_approve` 低风险自动通过 / `auto_reject` 硬性违规自动驳回 / `manual_review` 转人工
  - 风险分 = max(LLM 评分, 规则引擎确定性计分)，等级阈值由代码判定
- 📚 **RAG 知识库**：Milvus 向量库（远程standalone服务）+ 本机 Ollama Qwen3-Embedding 嵌入，检索「公司制度」与「历史相似案例」；每次审核自动回填案例（数据飞轮）
- ✅ **人工审批中心**：三栏流水线视图——「AI 审核中」（SUBMITTED 单据，15 秒自动刷新，可直接接管裁决）→ 经理初审（本部门）→ 财务终审；manager 限本部门、finance/admin 审全部，审批历史与 AI 审核共用同一时间线
- 💰 **财务打款登记**：approved → paid，真实转账在系统外完成
- 📏 **规则管理**：可视化维护审核规则（金额/发票/日期/重复发票），三级严重度 BLOCK / REVIEW / WARN；支持批量导入（JSON 直导 + 制度文档智能抽取）
- 🖥️ **工作流画布 + 人工接管 + 断点恢复**：详情抽屉实时显示各节点执行状态（单据解析 → 规则校验 ∥ RAG 检索 → 风险评估 → 终审裁决，3 秒轮询）；AI 执行期间经理/财务/管理员可随时直接批准/驳回——人审结果永远优先，AI 事后算出的结论只留档（节点标记「人审结果优先」），绝不覆盖；人审落定的瞬间未完成节点即标「人审结果优先」（AI 后续状态不得回写），已排队/被重投的审核任务开跑前发现人审已裁决则直接跳过（不烧 LLM、不清轨迹）；成功节点输出持久化为 checkpoint，中断/失败后「重新执行」从断点续跑（已完成节点直接复用，不重复调 LLM），worker 启动自动扫描重派卡死单
- 📊 **报表统计**：总览、月度趋势、分类占比（Redis 缓存，可选）

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 · MySQL（可切 PostgreSQL）· Redis（可选） |
| AI | LangGraph · LangChain · Kimi K3（对话+图片理解同款多模态，Kimi for Coding 订阅）· Qwen3-Embedding（本机 Ollama）· Milvus（远程向量库） |
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

### 1. 首次初始化（只跑一次）

```bash
# 依赖安装（项目根目录）
uv sync
cd frontend && npm install && cd ..   # 前端依赖

# 配置环境变量：复制 backend/.env.example 为根目录 .env 并填写
# 必填：DATABASE_URL / LLM_API_KEY（Kimi for Coding） / EMBEDDING_API_KEY（本机Ollama嵌入：先 ollama pull qwen3-embedding:8b，key 填任意占位值） / JWT_SECRET_KEY / SECRET_KEY
# 向量库（Milvus）：RAG需要一个可达的 Milvus 实例——连已有远程 standalone，
#   或参照官方文档本机起 standalone compose；.env 里配 MILVUS_URI=http://<host>:19530

# 初始化数据库（建表 + 4演示账号/6费用类别/8审核规则；新库走create_all无需迁移）
cd backend
uv run python scripts/init_db.py

# 初始化RAG知识库（RAG默认启用RAG_PROVIDER=milvus：需Milvus可达+本机Ollama嵌入；
# 不用时设RAG_PROVIDER=off——审核链路只用Kimi，RAG节点画布保留但返回空）
uv run python scripts/init_knowledge.py

# 旧库升级：已建库的老环境补断点恢复列（幂等，可重复执行）
uv run python scripts/migrate_v4.py
```

### 2. 日常启动（4 个终端）

MySQL 以服务方式运行中；②③在 `backend/` 目录（数据目录相对CWD落盘），④在 `frontend/` 目录。

```bash
# ① Redis（Celery队列依赖；容器已存在则 docker start <容器id>）
docker run -d -p 6379:6379 redis:7

# ② 后端API（Swagger文档 http://localhost:8000/api/docs）
uv run uvicorn app.main:app --reload --port 8000

# ③ AI审核worker（提交报销单后由它跑审核，Agent日志打在这里；Windows不支持prefork多进程池）
#    一次并行审3单：--pool=threads --concurrency=3（任务以I/O等待的LLM调用为主，线程池即可并行；
#    要严格单并发用 --pool=solo，或多开几个worker终端实现多进程并行）
uv run celery -A app.tasks.celery_app worker --loglevel=info --pool=threads --concurrency=3

# ④ 前端（frontend/ 目录；http://localhost:5173，/api 已代理到 8000）
npm run dev
```

- 提交依赖 Redis 与 worker ③：未启动时提交直接返回 503 明确报错（单据保持草稿，不降级）
- worker ③ 启动时自动扫描重派卡死单（SUBMITTED 超 15 分钟无节点进展，断点续跑不重调已完成的 LLM）；已在队列/执行中的单自动跳过，多 worker 同时启动不会重复派发

**日志说明** —— 每个业务请求（/api/*）在控制台只打一行：`方法 路径?query → 状态（耗时）+ 请求体`（password 等敏感字段打码）；uvicorn 原生访问行对 /api 去重不重复输出，前端轮询接口（画布 3 秒、铃铛 30 秒等）维持静音，非 /api 请求（静态资源等）访问行照常；控制台级别名带颜色（INFO 绿 / WARNING 黄 / ERROR 红），文件日志保持纯文本；完整日志（含全部访问日志）写入 `LOG_FILE`（默认 `backend/logs/app.log`，10MB×5 自动轮转；置空 `LOG_FILE=` 禁用；路径不可写自动降级为仅控制台）。`--reload` 父进程打印的 2-3 行横幅仍是 uvicorn 原生格式（它不加载应用代码），属正常现象。Celery worker 控制台日志也走这套格式与配色（prefork 子进程行带进程名前缀；每个任务的 received 行去重为一条）；worker 不写 LOG_FILE——多进程写同一文件会轮转冲突，需要落盘请给 worker 单独 `-f` 文件。双开后端实例请给各自配置不同的 `LOG_FILE`。

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
uv run pytest -m llm -v         # LLM 真实联调用例（需 LLM_API_KEY + 测试库）
```

## 暂未完成的业务

以下功能尚未实现或只有半成品，欢迎按此清单补全：

| 事项 | 现状 | 待完成内容 |
|---|---|---|
| 📎 发票文件上传 | ✅ 已完成 | `POST /api/uploads`（pdf/jpg/jpeg/png/docx，≤10MB）→ 落盘 `/uploads/yyyy/mm/`，静态文件服务 |
| 🔍 真实 OCR | ✅ 已完成 | 混合流水线：RapidOCR → 正则KIE（置信度≥0.85且关键字段齐全）或 Kimi K3 视觉兜底（K3原生多模态）→ 确定性业务校验（税号18/20位、不含税+税额=价税合计±0.01）；txt/docx 直读 |
| 📧 审核结果通知 | ✅ 已完成 | 站内信铃铛（30秒轮询）+ 邮件尽力而为；AI审核/人工审批/打款登记三个触发点 |
| 📤 报表导出 | ✅ 已完成 | `GET /api/reports/export` 返回4-sheet xlsx（总览/趋势/分类/明细）；finance/admin |
| 👥 用户管理页面 | ✅ 已完成 | `/users` admin页面：改角色/启停，禁止操作自己 |
| 🔗 多级审批流 | ✅ 已完成 | 固定两级链：经理初审（本部门）→ 财务终审；新增 `manager_approved` 状态、`approvals.step` 层级留痕、审批中心分待初审/待终审、admin 越级直批兜底、无经理部门自动跳过初审 |
| 🐳 容器化部署 | ✅ 已完成 | `docker compose up -d --build` 一条命令起全栈（PostgreSQL/Redis/backend/nginx 前端 + 一次性 init 建库种子账户）；uploads/日志全落卷，向量库为外部远程 Milvus（`MILVUS_URI`）；`--profile knowledge` 可选知识库初始化；见 `.env.docker.example` |
| 📥 规则/制度批量导入 | ✅ 已完成 | 规则管理页「导入规则」：① JSON 直导（与 Rule 表字段对齐，类别用 category_code；全量校验、逐行中文报错、有错全拒、原子写入，不碰向量库）② 制度文档 docx/pdf 智能导入（解析→LLM 抽取规则草稿带原文依据→人工预览编辑→确认写入 Rule 表 + 原文切块入 Milvus；追加 / 替换两模式，替换仅清 policies 制度库、绝不动 similar_cases 案例库） |
| 🗂️ 费用类别管理 | ✅ 已完成 | admin「类别管理」页：增/改/停用/删除；code 唯一且创建后不可改；删除自动停用并解绑绑定规则，被历史明细引用时转停用不物理删除；新增类别自动进入明细下拉 / 规则绑定 / 规则导入（OCR 关键词识别仍限六个内置类别，新类别手选） |
| 🖥️ 工作流画布 + 人工接管 + 断点恢复 | ✅ 已完成 | `GET /api/agent/executions/{id}` 提供逐节点轨迹（running/succeeded/failed/overridden，`_traced` 包装器 upsert 进 `agent_node_runs` 表）+ `can_retry` 显隐标记；详情抽屉自绘画布 3 秒轮询；`POST /api/approvals/takeover` 允许经理（限本部门）/财务/管理员对 SUBMITTED/PENDING/MANAGER_APPROVED 任意时刻裁决（财务/管理员对前两态批准直达终审，流水留痕 `[财务越级直批]`/`[管理员越级直批]`）——工作流落库段行锁守卫保证人审终局（AI 结论仅存 `ai_review` 流水留档、决策节点标记「人审结果优先」）；驳回必须填意见；**断点恢复**：成功节点输出存 `agent_node_runs.output_json`（TEXT，60KB 守卫），`POST /api/agent/executions/{id}/retry` 派发 resume=True 续跑（本人/admin/finance，执行中 409 防双跑），已成功节点注入 state 跳过不重调 LLM、画布保留原时间戳；worker_ready 信号启动自愈扫描（SUBMITTED 超 15 分钟宽限且无近期节点进展即重派，顺带恢复落库段崩溃的单据）；**排队可见性**：SUBMITTED 未开跑时轨迹接口附带队列探查（`app/tasks/queue_inspect.py` 只读 broker），画布显示「排队中·前面还有 N 单」或「已被 worker 领取·执行中」，仅当任务既不在队列、也未被领取时才提示可能丢失（可重跑/等自愈）；Redis/Celery 未启动时提交 503 快速失败（无进程内降级） |
| 🧪 测试覆盖 | ✅ 已完成 | 229 个 pytest 用例：认证 / 报销单 / 两级审批链（含 AI 执行中队列） / 通知 / 上传 / OCR流水线 / 用户 / 规则 / 类别 / 报表 / AI审核接口 / 规则导入（JSON直导 + 文档抽取）/ 节点埋点与人审优先竞态（落定标记·终态防回写·任务起点跳过） / 断点恢复（checkpoint 注入·跳过·续跑落库）/ 重跑接口 / worker自愈扫描 / Celery任务注册 / LLM超时配置 / 队列探查 全覆盖；DB 不可达时自动跳过 |
