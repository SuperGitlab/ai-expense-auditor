# AI Agent Expense Auditor

**English** | [简体中文](README.zh-CN.md)

An intelligent expense reimbursement review system built on **LangGraph multi-agent orchestration + RAG + a deterministic rules engine**.
AI handles the clear-cut claims (auto-approve / auto-reject) so humans can focus on the ones that truly need judgment — **the final verdict (approve / reject) is always executed by deterministic code; the LLM only advises**.

## Key Features

- 🔐 **Auth & RBAC**: JWT login, 4 roles (admin / finance / manager / employee), data visibility scoped by role
- 📄 **Expense management**: CRUD on claims with multiple line items, submit & cancel; amounts auto-summed; claim type auto-derived from line-item categories until manually chosen; drafts and rejected claims are editable and resubmittable
- 🤖 **AI review workflow**: triggered automatically on submit; LangGraph orchestrates 5 agents (Document → Rule ∥ RAG → Risk → Decision)
  - `auto_approve` low-risk auto-approve / `auto_reject` hard-violation auto-reject / `manual_review` escalate to human
  - Risk score = max(LLM score, deterministic rule score); risk levels are decided by code thresholds
- 📚 **RAG knowledge base**: Milvus (remote standalone) + local Ollama Qwen3-Embedding vectors, retrieving both company policies and similar historical cases; every review is written back as a new case (data flywheel)
- ✅ **Human approval center**: three-stage pipeline view — "AI reviewing" (SUBMITTED claims, auto-refresh every 15s, takeover available) → manager first review (own department) → finance final; manager sees own department, finance/admin see all; AI reviews and human approvals share one timeline
- 💰 **Payment registration**: approved → paid (the actual bank transfer happens outside the system)
- 📏 **Rule management**: maintain review rules (amount / invoice / date / duplicate invoice) with three severity levels: BLOCK / REVIEW / WARN; bulk import via JSON or policy-document extraction
- 🖥️ **Workflow canvas & human takeover & checkpoint resume**: the detail drawer shows live per-node execution status (Document → Rule ∥ RAG → Risk → Decision, 3s polling); while the AI is still running, manager/finance/admin can approve/reject at any time — the human verdict always wins and the late AI verdict is archived only (node marked "human-first"), never overwriting it; the moment a human decision lands, unfinished nodes are marked "human-first" (later AI status writes are rejected), and queued/redelivered review tasks skip themselves entirely when they find a human verdict already in place (no LLM calls, no trace wipe); succeeded node outputs are persisted as checkpoints, so an interrupted/failed run can "Re-run" from the breakpoint (completed nodes are reused, no repeated LLM calls), and the worker self-heals stuck claims on startup
- 📊 **Reports**: summary, monthly trends, category breakdown (Redis cache, optional)

## Tech Stack

| Layer | Technologies |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 · MySQL (PostgreSQL optional) · Redis (optional) |
| AI | LangGraph · LangChain · Kimi K3 (multimodal: chat & image understanding, via Kimi for Coding) · Qwen3-Embedding (local Ollama) · Milvus (remote vector store) |
| Frontend | Vue 3 · TypeScript · Vite · Element Plus · Pinia · vue-router |
| Tooling | uv (deps) · pytest · docker-compose (local PostgreSQL/Redis helpers) |

## AI Review Workflow

```
Submit claim (runs in background; API returns immediately)
        ↓
┌─ 1. DB preload: claim snapshot + rules + duplicate-invoice check ┐
│  2. LangGraph execution                                           │
│                                                                   │
│  DocumentAgent ──┬→ RuleAgent (pure-code engine)                  │
│                  └→ RAGAgent            (parallel fan-out)        │
│                        ↓ fan-in                                   │
│                  RiskAgent (0-100 score)                          │
│                        ↓                                          │
│                  DecisionAgent (final verdict in code)            │
├─ 3/4. Persist: AI fields + status transition + approval log ─────┤
└─ 5. Write case back to knowledge base (for future retrieval) ────┘
```

## Quick Start

### 1. First-time Setup (run once)

```bash
# Install dependencies (project root)
uv sync
cd frontend && npm install && cd ..   # frontend deps

# Configure env: copy backend/.env.example to .env in the project root and fill in
# Required: DATABASE_URL / LLM_API_KEY (Kimi for Coding) / EMBEDDING_API_KEY (local Ollama — run ollama pull qwen3-embedding:8b first; the key itself can be any placeholder) / JWT_SECRET_KEY / SECRET_KEY
# Vector store (Milvus): RAG needs a reachable Milvus instance — point at an existing
#   remote standalone, or start one locally via the official standalone compose;
#   set MILVUS_URI=http://<host>:19530 in .env

# Initialize the database (tables + 4 demo accounts / 6 categories / 8 rules; fresh DBs use create_all, no migration needed)
cd backend
uv run python scripts/init_db.py

# Seed the RAG knowledge base into Milvus (RAG is on by default via RAG_PROVIDER=milvus:
# requires a reachable Milvus + local Ollama embedding; set RAG_PROVIDER=off to disable —
# the review pipeline then uses Kimi only, the RAG node stays on the canvas but returns empty)
uv run python scripts/init_knowledge.py

# Legacy DB upgrade: adds the checkpoint-resume column (idempotent, safe to re-run)
uv run python scripts/migrate_v4.py
```

### 2. Daily Startup (4 terminals)

MySQL runs as a service; run ②③ inside `backend/` (data dirs are relative to CWD), ④ inside `frontend/`.

```bash
# ① Redis (Celery broker; if the container already exists: docker start <id>)
docker run -d -p 6379:6379 redis:7

# ② Backend API (Swagger docs at http://localhost:8000/api/docs)
uv run uvicorn app.main:app --reload --port 8000

# ③ AI review worker (runs reviews after each submit, agent logs land here; Windows does not support the prefork pool)
#    Reviews 3 claims in parallel: --pool=threads --concurrency=3 (tasks are mostly I/O-bound LLM calls;
#    for strict single-concurrency use --pool=solo, or open several worker terminals for multi-process parallelism)
uv run celery -A app.tasks.celery_app worker --loglevel=info --pool=threads --concurrency=3

# ④ Frontend (inside frontend/; http://localhost:5173, /api proxied to port 8000)
npm run dev
```

- Submits REQUIRE Redis ① and worker ③: when they are down, submit returns an explicit 503 and the claim stays in draft
- On startup, worker ③ auto-rescans and re-dispatches stuck claims (SUBMITTED >15min with no node progress; resumed from checkpoints); claims already queued or claimed by another worker are skipped, so several workers can start at once without double dispatch

**Logging** — each /api business request prints a single console line: `METHOD path?query → status (duration) + body` (sensitive fields such as passwords masked); uvicorn's raw access line is deduplicated for /api paths, frontend polling endpoints stay silent, non-/api requests (static assets etc.) keep their access lines, and level names are colorized (INFO green / WARNING yellow / ERROR red) while file logs stay plain text. The complete log (including all access lines) is written to `LOG_FILE` (default `backend/logs/app.log`, rotated at 10MB x 5; set `LOG_FILE=` to disable; unwritable path degrades to console-only). The 2-3 banner lines printed by the `--reload` parent process keep uvicorn's native format (it never imports the app). Celery worker console logs share the same format and colors (prefork child-process lines carry a process-name prefix; the duplicate per-task "received" line is deduplicated); the worker does not write LOG_FILE — concurrent processes rotating one file would corrupt it, give the worker its own `-f` file instead. Running two backend instances at once? Give each its own `LOG_FILE`.

### 3. Demo Accounts (created by init_db.py)

| Account | Password | Role | Permissions |
|---|---|---|---|
| admin | admin123 | Administrator | Everything (user & rule management) |
| finance01 | finance123 | Finance | Approve all claims, reports, payment registration |
| manager01 | manager123 | Manager | Approve claims from own department |
| employee01 | employee123 | Employee | Submit claims, view own claims |

### 4. Tests

```bash
uv run pytest -v                # Regular tests (rule-engine unit tests need no external deps; API tests auto-skip if DB unreachable)
uv run pytest -m llm -v         # Real-LLM integration tests (requires LLM_API_KEY + test DB)
```

## Work in Progress

Not yet implemented or half-done — contributions welcome:

| Item | Status | TODO |
|---|---|---|
| 📎 Invoice file upload | ✅ Done | `POST /api/uploads` (pdf/jpg/jpeg/png/docx, ≤10MB) → stored under `/uploads/yyyy/mm/`, served as static files |
| 🔍 Real OCR | ✅ Done | Hybrid pipeline: RapidOCR → regex KIE (conf≥0.85 & key fields complete) or Kimi K3 VLM fallback (K3 natively reads images) → deterministic validation (tax-ID 18/20 chars, excl+tax=total ±0.01); txt/docx read directly |
| 📧 Review notifications | ✅ Done | In-app bell notifications (30s polling) + best-effort email on AI review / human decision / payment |
| 📤 Report export | ✅ Done | `GET /api/reports/export` returns a 4-sheet xlsx (summary / trends / by-category / details); finance/admin |
| 👥 User management UI | ✅ Done | `/users` page for admin: role change + enable/disable, self-modification blocked |
| 🔗 Multi-level approval | ✅ Done | Fixed two-level chain: manager first review (own department) → finance final approval; new `manager_approved` status, `approvals.step` audit trail, approval center split into first/final queues, admin override, auto-skip when no manager in department |
| 🐳 Containerized deploy | ✅ Done | `docker compose up -d --build` starts the full stack (PostgreSQL/Redis/backend/nginx frontend + one-shot init & seed accounts); uploads/logs persisted in volumes, vector store is an external remote Milvus (`MILVUS_URI`); optional `--profile knowledge` init; see `.env.docker.example` |
| 📥 Rule & policy bulk import | ✅ Done | "Import" on the rule-management page: ① JSON direct import (fields mirror the Rule table, categories referenced by `category_code`; full validation with per-row errors, all-or-nothing atomic write, never touches the vector store) ② Policy-document import for docx/pdf (parse → LLM extracts rule drafts with verbatim quotes → human preview/edit → confirm: rules into MySQL + verbatim sections chunked into Milvus; append / replace modes, replace clears only the policies store and never touches similar_cases) |
| 🗂️ Expense-category management | ✅ Done | Admin "Categories" page: create / edit / disable / delete; code is unique and immutable after creation; deleting a category auto-disables and unbinds its rules, and falls back to disable-only (no physical delete) when historical expense items reference it; new categories appear automatically in item dropdowns, rule bindings and rule imports (OCR keyword mapping still covers the six built-in categories — new ones are manual-select) |
| 🖥️ Workflow canvas & human takeover & checkpoint resume | ✅ Done | `GET /api/agent/executions/{id}` serves per-node runs (running/succeeded/failed/overridden, upserted by `_traced` wrappers into `agent_node_runs`) plus a `can_retry` flag; self-drawn canvas in the detail drawer polls every 3s; `POST /api/approvals/takeover` lets manager (own dept) / finance / admin rule on SUBMITTED/PENDING/MANAGER_APPROVED anytime (finance/admin approving the first two states goes straight to final, logged as `[finance override]`/`[admin override]`) — row-lock guard in the workflow's persist step keeps the human verdict final (AI result archived as an `ai_review` record, decision node marked "human-first"); rejects require a comment; **checkpoint resume**: succeeded outputs stored in `agent_node_runs.output_json` (TEXT, 60KB guard), `POST /api/agent/executions/{id}/retry` dispatches resume=True (owner/admin/finance; 409 while running to prevent double dispatch) — succeeded nodes are injected into state and skipped without re-calling the LLM, canvas keeps original timestamps; a worker_ready signal self-heals stuck claims on startup (SUBMITTED past a 15-min grace with no recent node progress; also recovers claims whose persist step crashed); **queue visibility**: while SUBMITTED and not yet started, the executions endpoint probes the broker queue read-only (`app/tasks/queue_inspect.py`) and the canvas shows "queued — N claims ahead" / "claimed by worker (executing)", and only flags a task missing from both the queue and the unacked claims (possibly lost — retry or wait for the self-heal sweep); submit fails fast with 503 when Redis/Celery are down (no in-process fallback) |
| 🧪 Test coverage | ✅ Done | 229 pytest cases: auth / expenses / two-level approval chain (incl. AI-reviewing queue) / notifications / uploads / OCR pipeline / users / rules / categories / reports / agent endpoints / rule import (JSON + document extraction) / node tracing & human-priority race (decision-time marking · terminal-state write guard · task-level skip) / checkpoint resume (injection · skip · re-run landing) / retry endpoint / worker self-heal sweep / Celery task registration / LLM timeout config / queue inspection; DB-gated tests auto-skip when unreachable |

```
financial_reimbursement_review
├─ .claude
│  ├─ commands
│  │  ├─ add-logging.md
│  │  ├─ debug-with-logs.md
│  │  └─ review-logs.md
│  ├─ hooks
│  │  └─ check_python_logging.sh
│  └─ settings.json
├─ .dockerignore
├─ .python-version
├─ backend
│  ├─ app
│  │  ├─ agents
│  │  │  ├─ base_agent.py
│  │  │  ├─ decision_agent.py
│  │  │  ├─ document_agent.py
│  │  │  ├─ rag_agent.py
│  │  │  ├─ risk_agent.py
│  │  │  ├─ rule_agent.py
│  │  │  ├─ workflow.py
│  │  │  └─ __init__.py
│  │  ├─ api
│  │  │  ├─ deps.py
│  │  │  ├─ endpoints
│  │  │  │  ├─ agent.py
│  │  │  │  ├─ approvals.py
│  │  │  │  ├─ auth.py
│  │  │  │  ├─ categories.py
│  │  │  │  ├─ expenses.py
│  │  │  │  ├─ notifications.py
│  │  │  │  ├─ reports.py
│  │  │  │  ├─ rules.py
│  │  │  │  ├─ rule_import.py
│  │  │  │  ├─ uploads.py
│  │  │  │  ├─ users.py
│  │  │  │  └─ __init__.py
│  │  │  └─ __init__.py
│  │  ├─ config.py
│  │  ├─ database.py
│  │  ├─ db_migrations.py
│  │  ├─ logging_config.py
│  │  ├─ main.py
│  │  ├─ middleware.py
│  │  ├─ models
│  │  │  ├─ agent_run.py
│  │  │  ├─ approval.py
│  │  │  ├─ base.py
│  │  │  ├─ expense.py
│  │  │  ├─ notification.py
│  │  │  ├─ rule.py
│  │  │  ├─ user.py
│  │  │  └─ __init__.py
│  │  ├─ ocr
│  │  │  ├─ kie.py
│  │  │  ├─ pipeline.py
│  │  │  ├─ rapidocr_provider.py
│  │  │  ├─ types.py
│  │  │  ├─ validators.py
│  │  │  ├─ vlm_provider.py
│  │  │  └─ __init__.py
│  │  ├─ rag
│  │  │  ├─ embeddings.py
│  │  │  ├─ knowledge_base.py
│  │  │  ├─ retriever.py
│  │  │  ├─ vectorstore.py
│  │  │  └─ __init__.py
│  │  ├─ schemas
│  │  │  ├─ agent.py
│  │  │  ├─ approval.py
│  │  │  ├─ category.py
│  │  │  ├─ expense.py
│  │  │  ├─ notification.py
│  │  │  ├─ rule.py
│  │  │  ├─ rule_import.py
│  │  │  ├─ user.py
│  │  │  └─ __init__.py
│  │  ├─ services
│  │  │  ├─ approval_service.py
│  │  │  ├─ auth_service.py
│  │  │  ├─ expense_service.py
│  │  │  ├─ notification_service.py
│  │  │  ├─ report_service.py
│  │  │  ├─ rule_import_service.py
│  │  │  └─ __init__.py
│  │  ├─ tasks
│  │  │  ├─ queue_inspect.py
│  │  │  ├─ review.py
│  │  │  ├─ rule_extraction.py
│  │  │  └─ __init__.py
│  │  ├─ tools
│  │  │  ├─ database_tool.py
│  │  │  ├─ notification_tool.py
│  │  │  ├─ ocr_tool.py
│  │  │  └─ __init__.py
│  │  ├─ utils
│  │  │  ├─ cache.py
│  │  │  ├─ helpers.py
│  │  │  ├─ validators.py
│  │  │  └─ __init__.py
│  │  └─ __init__.py
│  ├─ Dockerfile
│  ├─ scripts
│  │  ├─ bulk_submit.py
│  │  ├─ init_db.py
│  │  ├─ init_knowledge.py
│  │  ├─ migrate_v2.py
│  │  ├─ migrate_v3.py
│  │  └─ migrate_v4.py
│  └─ tests
│     ├─ conftest.py
│     ├─ test_agents
│     │  ├─ test_document_agent_ocr.py
│     │  ├─ test_llm_timeout.py
│     │  ├─ test_ocr_writeback.py
│     │  ├─ test_workflow.py
│     │  ├─ test_workflow_nodes.py
│     │  ├─ test_workflow_notify.py
│     │  ├─ test_workflow_race.py
│     │  ├─ test_workflow_resume.py
│     │  ├─ test_workflow_skip.py
│     │  └─ __init__.py
│     ├─ test_api
│     │  ├─ test_agent.py
│     │  ├─ test_agent_executions.py
│     │  ├─ test_agent_retry.py
│     │  ├─ test_approvals.py
│     │  ├─ test_approvals_takeover.py
│     │  ├─ test_auth.py
│     │  ├─ test_categories.py
│     │  ├─ test_error_logging.py
│     │  ├─ test_expenses.py
│     │  ├─ test_notifications.py
│     │  ├─ test_reports.py
│     │  ├─ test_rules.py
│     │  ├─ test_rule_import_document.py
│     │  ├─ test_rule_import_json.py
│     │  ├─ test_uploads.py
│     │  ├─ test_users.py
│     │  └─ __init__.py
│     ├─ test_db_migrations.py
│     ├─ test_logging_config.py
│     ├─ test_migrations
│     │  ├─ test_migrate_v2.py
│     │  └─ __init__.py
│     ├─ test_ocr
│     │  ├─ test_config_ocr.py
│     │  ├─ test_kie.py
│     │  ├─ test_ocr_tool.py
│     │  ├─ test_pipeline.py
│     │  ├─ test_rapidocr_provider.py
│     │  ├─ test_validators.py
│     │  └─ test_vlm_provider.py
│     ├─ test_request_logging.py
│     ├─ test_services
│     │  ├─ test_knowledge_base_import.py
│     │  ├─ test_notification_service.py
│     │  ├─ test_rule_engine.py
│     │  ├─ test_rule_import_service.py
│     │  └─ __init__.py
│     ├─ test_tasks
│     │  ├─ test_queue_inspect.py
│     │  ├─ test_registration.py
│     │  ├─ test_review_task.py
│     │  ├─ test_sweep.py
│     │  └─ __init__.py
│     └─ __init__.py
├─ CLAUDE.md
├─ docker-compose.yml
├─ docs
│  ├─ architecture.drawio
│  ├─ paper
│  │  ├─ Agent面试考点.md
│  │  └─ 基于大语言模型多 Agent 协作的智能财务报销审核系统的设计与实现的毕业论文.md
│  └─ superpowers
│     ├─ plans
│     │  ├─ 2026-09-09-phase1-notifications-export-users.md
│     │  ├─ 2026-09-10-phase2-upload-ocr.md
│     │  ├─ 2026-09-11-phase3-two-level-approval.md
│     │  └─ 2026-09-11-phase4-docker-tests.md
│     └─ specs
│        └─ 2026-09-09-unfinished-features-design.md
├─ frontend
│  ├─ .dockerignore
│  ├─ Dockerfile
│  ├─ index.html
│  ├─ nginx.conf
│  ├─ package-lock.json
│  ├─ package.json
│  ├─ src
│  │  ├─ api
│  │  │  ├─ agent.ts
│  │  │  ├─ approval.ts
│  │  │  ├─ auth.ts
│  │  │  ├─ category.ts
│  │  │  ├─ expense.ts
│  │  │  ├─ notification.ts
│  │  │  ├─ report.ts
│  │  │  ├─ rule.ts
│  │  │  ├─ ruleImport.ts
│  │  │  ├─ upload.ts
│  │  │  └─ user.ts
│  │  ├─ App.vue
│  │  ├─ components
│  │  │  ├─ ExpenseDetailDrawer.vue
│  │  │  ├─ RuleDraftTable.vue
│  │  │  ├─ RuleImportDialog.vue
│  │  │  └─ WorkflowCanvas.vue
│  │  ├─ composables
│  │  │  └─ useClientPagination.ts
│  │  ├─ constants
│  │  │  └─ index.ts
│  │  ├─ layout
│  │  │  └─ MainLayout.vue
│  │  ├─ main.ts
│  │  ├─ router
│  │  │  └─ index.ts
│  │  ├─ stores
│  │  │  └─ user.ts
│  │  ├─ styles
│  │  │  └─ index.scss
│  │  ├─ types
│  │  │  └─ index.ts
│  │  ├─ utils
│  │  │  └─ request.ts
│  │  ├─ views
│  │  │  ├─ AllExpensesView.vue
│  │  │  ├─ ApprovalCenterView.vue
│  │  │  ├─ CategoryManagementView.vue
│  │  │  ├─ DashboardView.vue
│  │  │  ├─ ExpenseListView.vue
│  │  │  ├─ ExpenseSubmitView.vue
│  │  │  ├─ LoginView.vue
│  │  │  ├─ ReportsView.vue
│  │  │  ├─ RuleManagementView.vue
│  │  │  └─ UserManagementView.vue
│  │  └─ vite-env.d.ts
│  ├─ tsconfig.json
│  └─ vite.config.ts
├─ pyproject.toml
├─ README.md
├─ README.zh-CN.md
└─ uv.lock

```