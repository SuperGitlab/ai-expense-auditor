# 设计文档:完成 README「暂未完成的业务」全部 8 项

- 日期:2026-09-09
- 状态:已与用户逐节确认(4 节全部通过)
- 对应任务:README.md「Work in Progress」表列出的 8 项

## 背景与范围

系统现状:FastAPI + LangGraph 多 Agent 审核后端、Vue3 前端、单级人工终审(manage/finance 一次 decide 即终)、OCR 为占位文本、上传/导出/用户管理页/容器化/部分测试缺失。

本设计一次性覆盖 8 项,按 4 个阶段实施,每阶段可独立验收:

| 阶段 | 内容 | 依赖关系 |
|---|---|---|
| ① | 通知接线、报表导出、用户管理页面 | 三项独立,快速收益 |
| ② | 发票文件上传、OCR 混合流水线 | 上传先落地,OCR 才有本地文件可读 |
| ③ | 两级审批链 | 改动最大(状态机+工作流+审批中心),独立做透 |
| ④ | 容器化部署、存量模块测试补齐 | 工程收尾;新功能测试随各阶段写 |

## 已确认的三个关键决策

1. **多级审批 = 固定两级链**:经理初审 → 财务终审;不做金额阈值与可配置审批链。
2. **OCR = 混合流水线**(用户提供方案,按项目规模裁剪):RapidOCR 第一层 → 标准票走正则规则抽取、复杂票走 GLM-VLM 端到端抽取 → 确定性业务校验层。裁剪:用 `rapidocr-onnxruntime` 替代 PaddleOCR(免装 paddlepaddle);不做独立的倾斜矫正/印章区域检测(RapidOCR 自带方向处理,印章遮挡表现为低置信度/字段缺失,天然路由 VLM 分支)。
3. **通知 = 站内信 + 邮件双渠道**:站内信必有(落库),邮件尽力而为(复用现有 SMTP 工具,未配置降级日志)。

## 阶段①:通知接线 + 报表导出 + 用户管理页面

### 1.1 站内信 + 邮件通知

**数据模型**:新增 `backend/app/models/notification.py` → `notifications` 表:
`id`、`user_id`(FK users,收件人)、`title`(String 200)、`content`(Text)、`type`(String 20:ai_review / approval / payment)、`is_read`(Boolean,默认 False)、`created_at`(server_default)。同步导出到 `models/__init__.py`。

**服务层**:新增 `notification_service.send_notification(db, user_id, title, content, ntype)`:
1. 插入 Notification 行(必有);
2. 查收件人 email,尽力调用现有 `notification_tool.notify()`(未配 SMTP 秒回降级日志;失败仅告警,不影响主流程)。

**接口**:新增 `backend/app/api/endpoints/notifications.py`,prefix `/api/notifications`,所有登录角色可用:
- `GET /api/notifications` — 我的通知列表(分页,响应含 unread_count)
- `GET /api/notifications/unread-count`
- `POST /api/notifications/{id}/read`
- `POST /api/notifications/read-all`

**接线点(3 处,均在事务提交后调用)**:
- `workflow.py` AI 审核落库后 → 通知申请人:auto_approve「已自动通过」/ auto_reject「已自动驳回 + 原因」/ manual_review「转人工审批,等待部门经理初审」;
- `approval_service.decide` 人工审批后 → 通知申请人(初审通过待终审 / 终审通过 / 驳回 + 原因);
- `expense_service.pay_expense` 打款登记后 → 通知申请人。

**前端**:
- 新增 `api/notification.ts` + `types` 定义;
- `MainLayout.vue` 顶栏加🔔铃铛:`el-badge` 未读数红点 + `el-dropdown` 最近消息(未读加粗),点选标记已读、底部「全部已读」;30s 轮询刷新未读数。不单开消息页面。

**已知取舍**:邮件为同步发送,配置 SMTP 后审批接口最多增加 ~10s(工具内 timeout=10);无 SMTP 环境即时返回。演示阶段可接受。

### 1.2 报表导出(xlsx)

- 端点:`GET /api/reports/export?months=6`,权限 finance/admin(对齐 finance 已声明的 export 权限),返回 `StreamingResponse`(xlsx);`Content-Disposition` 用 `filename*=UTF-8''` 编码中文文件名。
- `report_service.export_report(db, months)`:openpyxl 生成 4 个 sheet — 总览(复用 get_summary)、月度趋势(get_trends)、分类占比(get_by_category)、报销明细(全量 expenses:单号/申请人/部门/类型/金额/状态/风险分/提交时间/通过时间);表头加粗、冻结首行、自适应列宽。
- 前端 `ReportsView.vue` 加「导出 Excel」按钮:axios `responseType: 'blob'` 下载(携带 token)。

### 1.3 用户管理页面

- 新增 `views/UserManagementView.vue` + 路由 `/users`(meta.roles: ['admin'])+ 侧边菜单项(admin 可见):用户表格(用户名/姓名/邮箱/部门/角色 tag/状态开关/创建时间),角色筛选下拉、分页;行内改角色(ElMessageBox 确认,防误触)、启停开关。
- 新增 `api/user.ts` 对接现有 `/api/users` 4 个端点。
- **后端补自我保护**([users.py](backend/app/api/endpoints/users.py) 现状缺失):`PATCH role`、`PATCH status` 拒绝对当前登录用户自己操作(400:不能修改自己的角色/不能禁用自己),避免 admin 把自己锁死。

## 阶段②:发票文件上传 + OCR 混合流水线

### 2.1 发票文件上传

**后端**:新增 `backend/app/api/endpoints/uploads.py`,`POST /api/uploads`(multipart `UploadFile`,CurrentUser):
- 校验:扩展名 ∈ `settings.ALLOWED_EXTENSIONS`(后缀转小写)、大小 ≤ `settings.MAX_FILE_SIZE`;
- 存储:`{UPLOAD_DIR}/{yyyy}/{mm}/{uuid}{ext}`(lifespan 已确保目录存在);
- 响应:`{url: "/uploads/2026/09/<uuid>.pdf", filename, size}`。

`main.py` 挂载 `app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR))`。

**配置变更**:默认 `ALLOWED_EXTENSIONS` 调整为 `.pdf .jpg .jpeg .png .docx`:
- 移除 `.doc`(老二进制格式,Python 无法解析、OCR 无法处理,保留即假功能);
- 新增 `.docx`(python-docx 提取文字)。已有 `.env` 显式配置的仍以 `.env` 为准。

**鉴权取舍**:`/uploads` 静态挂载无鉴权,路径含 uuid 不可猜测,演示项目可接受;鉴权下载端点列为后续工作。

**前端**:
- `ExpenseSubmitView.vue` 每条明细行加「上传发票」:调上传接口成功后回填该行 `invoice_url`,显示文件名 + 可点查看;保留手填 URL 输入框,两种方式并存;
- `ExpenseDetailDrawer.vue`:`invoice_url` 有值时,图片后缀用 `el-image`(缩略图 + 点击大图预览),其余显示下载链接。

### 2.2 OCR 混合流水线

新增包 `backend/app/ocr/`:

```
发票文件(本地路径 / URL;PDF 先经 PyMuPDF 逐页转图)
   ↓
【第一层 RapidOCR(rapidocr-onnxruntime)】→ 全文 + bbox + 置信度
   ↓
路由判定:平均置信度 ≥ OCR_MIN_CONFIDENCE(默认0.85) 且关键字段抽取完整
   ├─ 是 → 规则抽取(正则):发票号码/开票日期/不含税金额/税额/价税合计/购销方税号
   └─ 否 → GLM-VLM 端到端结构化抽取(VLM_MODEL_NAME 默认 glm-4.1v-flash,复用现有 GLM_API_KEY,返回 JSON)
   ↓
【业务校验层 · 确定性代码】
   税号 18/20 位数字 · 不含税 + 税额 = 价税合计(±0.01) · 日期合法 · 发票号与明细手填 invoice_no 一致
   ↓
OCRResult { fields, raw_text, confidence, method(rapidocr|vlm|placeholder), anomalies[] }
```

**模块划分**:
- `pipeline.py` — 编排与路由判定,导出 `extract_invoice(source) -> OCRResult`;
- `rapidocr_provider.py` — RapidOCR 封装(懒加载 import,未安装不崩);
- `vlm_provider.py` — GLM 视觉模型调用(langchain-openai,图片 base64;提示词要求返回 JSON,解析失败降级);
- `validators.py` — 业务校验(纯函数);
- `kie.py` — 增值税发票字段正则抽取(纯函数)。

**降级链**:RapidOCR 未安装/执行失败 → VLM;VLM 失败/未配 key → 返回现有占位文本。任何一层失败不抛异常、不影响提交主流程。

**接入点**:重写 [ocr_tool.py](backend/app/tools/ocr_tool.py) 的图片/PDF 分支(`read_invoice_text` 签名不变):文本类直读不变;图片/PDF 走 pipeline;docx 由 python-docx 提取文字后**跳过 OCR 层**、直接进规则抽取与业务校验。三类均返回「原文 + 抽取字段 JSON + 校验异常」拼装的文本,供 DocumentAgent 纳入分析。

**回写**:OCR 校验结论进入工作流 state;`workflow.run` 落库步骤按校验结果更新 `expense_items.invoice_verified`(校验全过 = True)。校验异常写入给 DocumentAgent 的文本,LLM 可感知并纳入风险分析。

**配置新增**:`OCR_PROVIDER`(默认 `hybrid`,设 `off` 时保持占位行为)、`VLM_MODEL_NAME`(默认 `glm-4.1v-flash`)、`OCR_MIN_CONFIDENCE`(默认 `0.85`)。

## 阶段③:两级审批链(固定:经理初审 → 财务终审)

### 状态机

新增 `ExpenseStatus.MANAGER_APPROVED = "manager_approved"`(经理已初审,待财务终审):

```
SUBMITTED ──AI auto_approve──→ APPROVED(自动通过不进链,不变)
        ├─AI auto_reject───→ REJECTED(不变)
        └─AI manual_review─→ PENDING(待经理初审)
                               │ manager approve → MANAGER_APPROVED(待财务终审)
                               │                    │ finance/admin approve → APPROVED(此刻写 approved_at)
                               └── 任一级 reject ──→ REJECTED(附原因,可改后重提)
```

### 决策规则(`approval_service.decide` 重写)

| 角色 | 可操作状态 | approve 效果 | reject 效果 |
|---|---|---|---|
| manager | PENDING(仅本部门) | → MANAGER_APPROVED | → REJECTED |
| finance | MANAGER_APPROVED(全部) | → APPROVED(终审,写 approved_at) | → REJECTED |
| admin | PENDING、MANAGER_APPROVED | 越级直批 → APPROVED(留痕) | → REJECTED |

- finance 不可操作 PENDING(正常流程必须先过经理);admin 越级是为系统永不卡死,审批记录可见。
- **自动跳过经理初审**(确定性代码,在 manual_review 落库时判定):① 申请人本人是 manager 角色(不能自审自己);② 申请人部门无在职 manager。命中任一条 → 直接落 MANAGER_APPROVED。
- `approved_at` 仅在到达 APPROVED 时写入(auto_approve 同现状)。

### 数据与记录

- `approvals` 表新增 `step` 列(String 20,nullable,取值 manager/finance),动作枚举沿用 APPROVE/REJECT(SUBMIT/AI_REVIEW 不变);时间线按 step 渲染「初审通过(经理)/ 终审通过(财务)」。
- `cancel_expense` 可取消状态收窄为 DRAFT / SUBMITTED / PENDING;MANAGER_APPROVED 之后不可自行取消(已进财务队列)。
- `pay_expense` 不变(仍仅 APPROVED → PAID)。

### 存量库迁移

项目未用 Alembic,提供幂等脚本 `backend/scripts/migrate_v2.py`:
- MySQL:`ALTER TABLE expenses MODIFY status ENUM(... , 'manager_approved') NOT NULL`;
- `ALTER TABLE approvals ADD COLUMN step VARCHAR(20) NULL`(存在则跳过;PG 用 `ALTER TYPE ... ADD VALUE` + `ADD COLUMN IF NOT EXISTS`)。
开发库亦可直接重建(`init_db.py` 建新结构)。

### 触及面

- `workflow.py` 第 4 步:manual_review 时按跳过规则落 PENDING 或 MANAGER_APPROVED;
- `list_pending`:manager 见 PENDING(本部门);finance/admin 见 PENDING + MANAGER_APPROVED;
- 前端:审批中心分「待初审 / 待终审」两组;`constants` 补 manager_approved 状态名/颜色;详情抽屉时间线按 step 渲染;「我的报销」列表状态列适配;通知文案区分初审/终审。

## 阶段④:容器化部署 + 测试收尾

### 容器化

- `backend/Dockerfile`:`python:3.12-slim` + uv(官方镜像 copy 安装);`uv sync --frozen --no-dev`;工作目录设 `backend/`(使 `./data ./uploads ./logs` 相对路径照常);CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`。
- `frontend/Dockerfile`:两阶段 — `node:20-alpine` 执行 `npm ci && npm run build` → 产物拷入 `nginx:alpine`。
- `frontend/nginx.conf`:SPA history 模式 `try_files ... /index.html`;`/api`、`/uploads` 反代 `http://backend:8000`。
- `docker-compose.yml` 扩充(保留现有 db/redis):
  - `backend`:env 注入 `DATABASE_URL=postgresql+psycopg2://user:password@db:5432/expense_db` 等;depends_on db/redis(healthy);挂载 `uploads/ data/ logs/` 卷;healthcheck 复用现有 `/health` 端点(容器内 `python -c "import urllib.request; ..."` 探测,不装 curl);
  - `frontend`:映射宿主 80 端口,depends_on backend;
  - `init`:一次性任务跑 `scripts/init_db.py`(建表+种子账户);`--profile knowledge` 下可选跑 `scripts/init_knowledge.py`(需 GLM key)。
- 配套:根目录与前后端 `.dockerignore`、`.env.docker.example`;compose 默认 PostgreSQL(psycopg2 已在依赖),README 注明切 MySQL 仅改 `DATABASE_URL`。
- Chroma 数据、上传文件全部落卷,容器重建不丢。

### 测试补齐

新功能测试随各阶段编写(通知触发/已读、上传校验、OCR validators/kie/路由 mock、审批链矩阵、导出)。阶段④补存量欠账,全部沿用 conftest 模式(DB 不可达自动跳过):

| 测试文件 | 覆盖 |
|---|---|
| test_api/test_users.py | 列表/筛选/改角色/启停/自我保护/权限 |
| test_api/test_rules.py | 规则 CRUD、admin 鉴权 |
| test_api/test_categories.py | 类别查询与管理 |
| test_api/test_reports.py | 三接口 + 导出 xlsx、finance/admin 鉴权 |
| test_api/test_agent.py | workflow 信息接口、review 状态门槛(monkeypatch 掉真工作流) |

## 汇总

### 新增依赖(由用户执行安装)

```bash
uv add openpyxl rapidocr-onnxruntime pymupdf python-docx
```

前端无新增依赖。

### 配置项新增(`.env.example` 同步)

| 配置 | 默认值 | 说明 |
|---|---|---|
| OCR_PROVIDER | hybrid | off 时保持占位行为 |
| VLM_MODEL_NAME | glm-4.1v-flash | OCR VLM 兜底模型 |
| OCR_MIN_CONFIDENCE | 0.85 | RapidOCR 分支的路由阈值 |

`ALLOWED_EXTENSIONS` 默认值调整(见 2.1)。

### 数据库变更汇总

1. 新表 `notifications`;
2. `approvals` 加 `step` 列;
3. `expenses.status` 枚举加 `manager_approved`。
存量库跑 `scripts/migrate_v2.py`(幂等),开发库可重建。

### 错误处理总原则

- 通知:任何失败不阻塞主流程(降级日志);
- OCR:逐层降级(rapidocr → vlm → placeholder),永不抛异常;
- 审批链跳过规则:纯代码判定,LLM 不参与;
- 上传:扩展名/大小校验 400,清晰报错。

### 明确不做(Out of Scope)

- 金额阈值审批 / 可配置审批链;
- PaddleOCR、印章检测、倾斜矫正独立建模;
- 站内信 WebSocket 实时推送(轮询足够);
- `/uploads` 鉴权下载端点;
- Alembic 迁移框架引入;
- 测试覆盖率数字指标(以补齐上述模块用例为准)。

### 验收标准(对应 README 8 项)

1. 上传:提交页可传 jpg/png/pdf/docx,超限/非法扩展名被拒,详情抽屉可预览/下载;
2. OCR:发票图片/PDF 提取出结构化字段并经业务校验,校验通过回写 `invoice_verified`,无 OCR 依赖时系统照常运行;
3. 通知:AI 审核、人工审批、打款后,申请人铃铛收到站内信;配 SMTP 时同步收到邮件;
4. 导出:finance/admin 一键下载 4-sheet xlsx;
5. 用户管理:admin 可在页面改角色/启停用户,无法操作自己;
6. 审批链:转人工单据经理初审 → 财务终审才 APPROVED,两级均可驳回,跳过规则生效,时间线完整;
7. 容器化:`docker compose up` 一条命令起全栈(db/redis/backend/frontend),健康检查通过;
8. 测试:`uv run pytest` 覆盖 users/rules/categories/reports/agent 及全部新功能,DB 不可达时自动跳过。
