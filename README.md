# AI Agent Expense Auditor

**English** | [简体中文](README.zh-CN.md)

An intelligent expense reimbursement review system built on **LangGraph multi-agent orchestration + RAG + a deterministic rules engine**.
AI handles the clear-cut claims (auto-approve / auto-reject) so humans can focus on the ones that truly need judgment — **the final verdict (approve / reject) is always executed by deterministic code; the LLM only advises**.

## Key Features

- 🔐 **Auth & RBAC**: JWT login, 4 roles (admin / finance / manager / employee), data visibility scoped by role
- 📄 **Expense management**: CRUD on claims with multiple line items, submit & cancel; amounts auto-summed; drafts and rejected claims are editable and resubmittable
- 🤖 **AI review workflow**: triggered automatically on submit; LangGraph orchestrates 5 agents (Document → Rule ∥ RAG → Risk → Decision)
  - `auto_approve` low-risk auto-approve / `auto_reject` hard-violation auto-reject / `manual_review` escalate to human
  - Risk score = max(LLM score, deterministic rule score); risk levels are decided by code thresholds
- 📚 **RAG knowledge base**: Milvus (remote standalone) + GLM embeddings, retrieving both company policies and similar historical cases; every review is written back as a new case (data flywheel)
- ✅ **Human approval center**: manager sees own department, finance/admin see all; AI reviews and human approvals share one timeline
- 💰 **Payment registration**: approved → paid (the actual bank transfer happens outside the system)
- 📏 **Rule management**: maintain review rules (amount / invoice / date / duplicate invoice) with three severity levels: BLOCK / REVIEW / WARN; bulk import via JSON or policy-document extraction
- 🖥️ **Workflow canvas & human takeover & checkpoint resume**: the detail drawer shows live per-node execution status (Document → Rule ∥ RAG → Risk → Decision, 3s polling); while the AI is still running, manager/finance/admin can approve/reject at any time — the human verdict always wins and the late AI verdict is archived only (node marked "human-first"), never overwriting it; succeeded node outputs are persisted as checkpoints, so an interrupted/failed run can "Re-run" from the breakpoint (completed nodes are reused, no repeated LLM calls), and the worker self-heals stuck claims on startup
- 📊 **Reports**: summary, monthly trends, category breakdown (Redis cache, optional)

## Tech Stack

| Layer | Technologies |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 · MySQL (PostgreSQL optional) · Redis (optional) |
| AI | LangGraph · LangChain · GLM (glm-5.1 chat + embedding-3 vectors) · Milvus (remote vector store) |
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
# Required: DATABASE_URL / GLM_API_KEY / JWT_SECRET_KEY / SECRET_KEY
# Vector store (Milvus): RAG needs a reachable Milvus instance — point at an existing
#   remote standalone, or start one locally via the official standalone compose;
#   set MILVUS_URI=http://<host>:19530 in .env

# Initialize the database (tables + 4 demo accounts / 6 categories / 8 rules; fresh DBs use create_all, no migration needed)
cd backend
uv run python scripts/init_db.py

# Seed the RAG knowledge base into Milvus (sample finance policies; requires GLM_API_KEY)
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

# ③ AI review worker (runs reviews after each submit, agent logs land here; Windows requires --pool=solo)
uv run celery -A app.tasks.celery_app worker --loglevel=info --pool=solo

# ④ Frontend (inside frontend/; http://localhost:5173, /api proxied to port 8000)
npm run dev
```

- Submits REQUIRE Redis ① and worker ③: when they are down, submit returns an explicit 503 and the claim stays in draft
- On startup, worker ③ auto-rescans and re-dispatches stuck claims (SUBMITTED >15min with no node progress; resumed from checkpoints)

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
uv run pytest -m llm -v         # Real-LLM integration tests (requires GLM_API_KEY + test DB)
```

## Work in Progress

Not yet implemented or half-done — contributions welcome:

| Item | Status | TODO |
|---|---|---|
| 📎 Invoice file upload | ✅ Done | `POST /api/uploads` (pdf/jpg/jpeg/png/docx, ≤10MB) → stored under `/uploads/yyyy/mm/`, served as static files |
| 🔍 Real OCR | ✅ Done | Hybrid pipeline: RapidOCR → regex KIE (conf≥0.85 & key fields complete) or GLM-VLM fallback → deterministic validation (tax-ID 18/20 chars, excl+tax=total ±0.01); txt/docx read directly |
| 📧 Review notifications | ✅ Done | In-app bell notifications (30s polling) + best-effort email on AI review / human decision / payment |
| 📤 Report export | ✅ Done | `GET /api/reports/export` returns a 4-sheet xlsx (summary / trends / by-category / details); finance/admin |
| 👥 User management UI | ✅ Done | `/users` page for admin: role change + enable/disable, self-modification blocked |
| 🔗 Multi-level approval | ✅ Done | Fixed two-level chain: manager first review (own department) → finance final approval; new `manager_approved` status, `approvals.step` audit trail, approval center split into first/final queues, admin override, auto-skip when no manager in department |
| 🐳 Containerized deploy | ✅ Done | `docker compose up -d --build` starts the full stack (PostgreSQL/Redis/backend/nginx frontend + one-shot init & seed accounts); uploads/logs persisted in volumes, vector store is an external remote Milvus (`MILVUS_URI`); optional `--profile knowledge` init; see `.env.docker.example` |
| 📥 Rule & policy bulk import | ✅ Done | "Import" on the rule-management page: ① JSON direct import (fields mirror the Rule table, categories referenced by `category_code`; full validation with per-row errors, all-or-nothing atomic write, never touches the vector store) ② Policy-document import for docx/pdf (parse → LLM extracts rule drafts with verbatim quotes → human preview/edit → confirm: rules into MySQL + verbatim sections chunked into Milvus; append / replace modes, replace clears only the policies store and never touches similar_cases) |
| 🗂️ Expense-category management | ✅ Done | Admin "Categories" page: create / edit / disable / delete; code is unique and immutable after creation; deleting a category auto-disables and unbinds its rules, and falls back to disable-only (no physical delete) when historical expense items reference it; new categories appear automatically in item dropdowns, rule bindings and rule imports (OCR keyword mapping still covers the six built-in categories — new ones are manual-select) |
| 🖥️ Workflow canvas & human takeover & checkpoint resume | ✅ Done | `GET /api/agent/executions/{id}` serves per-node runs (running/succeeded/failed/overridden, upserted by `_traced` wrappers into `agent_node_runs`) plus a `can_retry` flag; self-drawn canvas in the detail drawer polls every 3s; `POST /api/approvals/takeover` lets manager (own dept) / finance / admin rule on SUBMITTED/PENDING/MANAGER_APPROVED anytime (finance/admin approving the first two states goes straight to final, logged as `[finance override]`/`[admin override]`) — row-lock guard in the workflow's persist step keeps the human verdict final (AI result archived as an `ai_review` record, decision node marked "human-first"); rejects require a comment; **checkpoint resume**: succeeded outputs stored in `agent_node_runs.output_json` (TEXT, 60KB guard), `POST /api/agent/executions/{id}/retry` dispatches resume=True (owner/admin/finance; 409 while running to prevent double dispatch) — succeeded nodes are injected into state and skipped without re-calling the LLM, canvas keeps original timestamps; a worker_ready signal self-heals stuck claims on startup (SUBMITTED past a 15-min grace with no recent node progress; also recovers claims whose persist step crashed); submit fails fast with 503 when Redis/Celery are down (no in-process fallback) |
| 🧪 Test coverage | ✅ Done | 214 pytest cases: auth / expenses / two-level approval chain / notifications / uploads / OCR pipeline / users / rules / categories / reports / agent endpoints / rule import (JSON + document extraction) / node tracing & human-priority race / checkpoint resume (injection · skip · re-run landing) / retry endpoint / worker self-heal sweep / Celery task registration; DB-gated tests auto-skip when unreachable |
