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
- 📚 **RAG knowledge base**: ChromaDB + GLM embeddings, retrieving both company policies and similar historical cases; every review is written back as a new case (data flywheel)
- ✅ **Human approval center**: manager sees own department, finance/admin see all; AI reviews and human approvals share one timeline
- 💰 **Payment registration**: approved → paid (the actual bank transfer happens outside the system)
- 📏 **Rule management**: maintain review rules (amount / invoice / date / duplicate invoice) with three severity levels: BLOCK / REVIEW / WARN
- 📊 **Reports**: summary, monthly trends, category breakdown (Redis cache, optional)

## Tech Stack

| Layer | Technologies |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 · MySQL (PostgreSQL optional) · Redis (optional) |
| AI | LangGraph · LangChain · GLM (glm-5.1 chat + embedding-3 vectors) · ChromaDB |
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

### 1. Backend

```bash
# Install dependencies (project root)
uv sync

# Configure env: copy backend/.env.example to .env in the project root and fill in
# Required: DATABASE_URL / GLM_API_KEY / JWT_SECRET_KEY / SECRET_KEY

# Initialize the database (tables + 4 demo accounts / 6 categories / 8 rules)
cd backend
uv run python scripts/init_db.py

# Seed the RAG knowledge base (sample finance policies; requires GLM_API_KEY)
uv run python scripts/init_knowledge.py

# Start the server (must run inside backend/ — data dirs are relative to CWD)
uv run uvicorn app.main:app --reload --port 8000
```

Swagger docs: <http://localhost:8000/api/docs>

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (/api is proxied to port 8000)
```

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
| 🔗 Multi-level approval | ❌ Not designed | Currently a single-step final decision (manager or finance); no manager → finance approval chain |
| 🐳 Containerized deploy | ⚠️ Partial | docker-compose only has PostgreSQL/Redis helpers; no Dockerfile for backend/frontend, no nginx config |
| 🧪 Test coverage | ⚠️ Partial | No test cases for users / rules / categories / reports / agent endpoints; workflow tests require `-m llm` |
