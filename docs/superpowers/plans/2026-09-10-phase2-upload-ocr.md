# 阶段② 实施计划：发票文件上传 + OCR 混合流水线

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地规格 [2026-09-09-unfinished-features-design.md](../specs/2026-09-09-unfinished-features-design.md) 的阶段②——`POST /api/uploads` 发票上传 + OCR 混合流水线（RapidOCR → 正则 KIE / GLM-VLM → 确定性业务校验），校验结论回写 `expense_items.invoice_verified`。

**Architecture:** 新增 `backend/app/ocr/` 包（pipeline 编排 + rapidocr/vlm 两个 provider + kie/validators 两个纯函数模块 + types）。上传文件落 `{UPLOAD_DIR}/{yyyy}/{mm}/{uuid}{ext}`，`/uploads` 静态挂载（无鉴权，路径含 uuid 不可猜测，演示项目可接受）。`ocr_tool.read_invoice_text` 签名不变、内部改走新流水线；docx/txt 直读文字后跳过 OCR 层、直接进 KIE + 业务校验。降级链：rapidocr 失败→VLM；VLM 失败→占位；`OCR_PROVIDER=off`→保持占位行为。任何一层失败不抛异常、不影响提交主流程。

**Tech Stack:** FastAPI(UploadFile/StaticFiles) · rapidocr-onnxruntime · PyMuPDF(PDF→图) · python-docx · langchain-openai(GLM-VLM) · openpyxl 已有

**重要约束:**
- 依赖已由用户安装（rapidocr-onnxruntime / pymupdf / python-docx），计划不再列安装命令
- 后端测试命令（在 `backend/` 目录执行）：
  `TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest <路径> -v`
- 纯函数测试（kie/validators/pipeline/vlm 解析/ocr_tool）不需要 DB，直接 `uv run pytest <路径> -v` 即可（conftest 在 DB 不可达时自动 skip DB 用例）
- 真实 RapidOCR / 真实 VLM 的用例标记 `@pytest.mark.llm`（默认 deselect）
- 前端无测试框架，验证方式为 `cd frontend && npm run build`
- `uv run pytest tests/ -m llm -v` 可手动启用真实模型用例（需 .env 的 GLM_API_KEY）

---

## 文件结构

| 动作 | 文件 | 职责 |
|---|---|---|
| Create | `backend/app/api/endpoints/uploads.py` | POST /api/uploads：扩展名/大小校验、落盘、返回 url |
| Modify | `backend/app/main.py` | 注册 uploads 路由 + 静态挂载 /uploads |
| Modify | `backend/app/config.py` | 新增 OCR_PROVIDER/VLM_MODEL_NAME/OCR_MIN_CONFIDENCE；ALLOWED_EXTENSIONS 默认移除 .doc |
| Create | `backend/app/ocr/__init__.py` | 包导出 |
| Create | `backend/app/ocr/types.py` | OCRResult 数据类 |
| Create | `backend/app/ocr/validators.py` | 业务校验纯函数 |
| Create | `backend/app/ocr/kie.py` | 增值税发票正则抽取纯函数 |
| Create | `backend/app/ocr/rapidocr_provider.py` | RapidOCR 封装（懒加载、PDF 转图） |
| Create | `backend/app/ocr/vlm_provider.py` | GLM 视觉模型抽取（base64 图片 → JSON） |
| Create | `backend/app/ocr/pipeline.py` | 编排与路由判定 extract_invoice |
| Modify | `backend/app/tools/ocr_tool.py` | 重写：read_invoice_ocr 新函数 + read_invoice_text 拼装 |
| Modify | `backend/app/agents/document_agent.py` | 收集逐明细 ocr_items |
| Modify | `backend/app/agents/workflow.py` | 落库回写 expense_items.invoice_verified |
| Create | `frontend/src/api/upload.ts` | 上传 API |
| Modify | `frontend/src/views/ExpenseSubmitView.vue` | 明细行「上传发票」 |
| Modify | `frontend/src/components/ExpenseDetailDrawer.vue` | 发票文件预览/下载 |
| Modify | `frontend/vite.config.ts` | /uploads 代理 |
| Modify | `README.md` / `README.zh-CN.md` | 更新两行 |
| Test | `backend/tests/test_api/test_uploads.py`、`tests/test_ocr/test_config_ocr.py`、`test_validators.py`、`test_kie.py`、`test_rapidocr_provider.py`、`test_vlm_provider.py`、`test_pipeline.py`、`test_ocr_tool.py`、`tests/test_agents/test_document_agent_ocr.py`、`test_ocr_writeback.py` | 本阶段用例 |

样例票面文本（多模块测试共用，写测试时照抄）：

```
江苏增值税电子普通发票
购买方名称：测试科技有限公司  纳税人识别号：91320100MA1EXAMPLE
销售方名称：南京某某商贸有限公司  纳税人识别号：91320100KUNOWN1234
开票日期：2026年08月15日
项目名称 规格 单价 金额 税率 税额
*信息技术服务*平台服务费        ¥95.00    6%  ¥5.00
合 计                        ¥95.00        ¥5.00
价税合计（大写） 壹佰元整      ¥100.00
发票号码：25617000000123456789
```

注意其中税号故意构造：`91320100MA1EXAMPLE` 含字母共 18 位（购买方合法）、`91320100KUNOWN1234` 19 位（销售方——校验用例专门断言 19 位报异常）。

---

### Task 0: 前置准备

- [ ] **Step 1: 创建功能分支**

```bash
git checkout -b feat/phase2-upload-ocr
```

---

### Task 1: 上传端点 + 静态挂载

**Files:**
- Create: `backend/app/api/endpoints/uploads.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api/test_uploads.py`

- [ ] **Step 1: 写失败测试**

```python
"""
上传接口测试
扩展名/大小校验、落盘、未登录401
"""
import base64

from app.config import settings

from tests.conftest import register_and_login, requires_db

# 1x1 透明PNG
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@requires_db
def test_upload_requires_auth(client):
    resp = client.post("/api/uploads", files={"file": ("a.png", PNG_1PX, "image/png")})
    assert resp.status_code == 401


@requires_db
def test_upload_png_ok(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    headers = register_and_login(client, "up_e1")
    resp = client.post(
        "/api/uploads", files={"file": ("inv.png", PNG_1PX, "image/png")}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"].startswith("/uploads/") and body["url"].endswith(".png")
    assert body["filename"] == "inv.png"
    assert body["size"] == len(PNG_1PX)
    # 文件确实落到 UPLOAD_DIR
    local = tmp_path / body["url"][len("/uploads/"):]
    assert local.exists() and local.read_bytes() == PNG_1PX


@requires_db
def test_upload_bad_extension(client, db_session, monkeypatch):
    import tempfile
    monkeypatch.setattr(settings, "UPLOAD_DIR", tempfile.mkdtemp())
    headers = register_and_login(client, "up_e2")
    resp = client.post(
        "/api/uploads", files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 400  # 扩展名校验先于落盘拒绝


@requires_db
def test_upload_too_large(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_FILE_SIZE", 10)
    headers = register_and_login(client, "up_e3")
    resp = client.post(
        "/api/uploads", files={"file": ("big.png", b"x" * 11, "image/png")}, headers=headers
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest tests/test_api/test_uploads.py -v`
Expected: 4 个用例 FAIL/404（路由不存在）

- [ ] **Step 3: 实现端点**

`backend/app/api/endpoints/uploads.py`:

```python
"""
发票文件上传接口
multipart上传 → 扩展名/大小校验 → 落盘 {UPLOAD_DIR}/{yyyy}/{mm}/{uuid}{ext}
"""
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.deps import CurrentUser
from app.config import settings

router = APIRouter(prefix="/api/uploads", tags=["文件上传"])


@router.post("", status_code=201)
async def upload_invoice(file: UploadFile, current_user: CurrentUser):
    """上传发票文件，返回可访问的相对URL"""
    ext = Path(file.filename or "").suffix.lower()
    allowed = [e.lower() for e in settings.ALLOWED_EXTENSIONS]
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext or '(无扩展名)'}，允许：{' '.join(allowed)}",
        )

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件超过大小限制 {settings.MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    now = datetime.now()
    rel_dir = Path(str(now.year)) / f"{now.month:02d}"
    target_dir = Path(settings.UPLOAD_DIR) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (target_dir / name).write_bytes(content)

    return {
        "url": f"/uploads/{rel_dir.as_posix()}/{name}",
        "filename": file.filename,
        "size": len(content),
    }
```

`backend/app/main.py`：路由挂载 import 行与 include 行各加 `uploads`（按字母序排在 users 之后）：

```python
from app.api.endpoints import (agent, approvals, auth, categories, expenses,  # noqa: E402
                               notifications, reports, rules, uploads, users)
```

```python
app.include_router(notifications.router)
app.include_router(uploads.router)
```

`backend/app/main.py` 顶部 import 区（现有 fastapi import 附近）加，并在 `app = FastAPI(...)` 创建之后、路由挂载之前加静态挂载（mount 构造即校验目录，必须先 mkdir；lifespan 里的 mkdir 保留不动，二者幂等）：

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path
```

```python
# 上传文件静态服务（无鉴权：路径含uuid不可猜测，演示项目可接受）
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
```

（`Path` 若 main.py 已 import 则不重复；`settings` 已 import。）

- [ ] **Step 4: 运行确认通过**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_api/test_uploads.py -v`（TESTURL 前缀同上）
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/endpoints/uploads.py backend/app/main.py backend/tests/test_api/test_uploads.py
git commit -m "feat(uploads): 发票文件上传接口+静态服务(pdf/jpg/png/docx)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: OCR 配置

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_ocr/test_config_ocr.py`

- [ ] **Step 1: 写失败测试**

```python
"""
OCR相关配置默认值测试
不依赖DB/env（_env_file=None 只测类默认）
"""
from app.config import Settings


def _defaults() -> Settings:
    return Settings(
        _env_file=None,
        SECRET_KEY="x", GLM_API_KEY="x", JWT_SECRET_KEY="x",
    )


def test_ocr_defaults():
    s = _defaults()
    assert s.OCR_PROVIDER == "hybrid"
    assert s.VLM_MODEL_NAME == "glm-4.1v-flash"
    assert s.OCR_MIN_CONFIDENCE == 0.85


def test_allowed_extensions_default():
    s = _defaults()
    assert ".doc" not in s.ALLOWED_EXTENSIONS  # 老二进制格式移除
    for ext in (".pdf", ".jpg", ".jpeg", ".png", ".docx"):
        assert ext in s.ALLOWED_EXTENSIONS
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_config_ocr.py -v`
Expected: FAIL `AttributeError: 'Settings' object has no attribute 'OCR_PROVIDER'`（或收集 ImportError——tests/test_ocr/ 目录无 `__init__.py` 也能收集，失败即对）

- [ ] **Step 3: 实现**

`backend/app/config.py` 的 LLM 配置区（`MODEL_NAME` 行之后）加：

```python
    # OCR混合流水线配置
    OCR_PROVIDER: str = "hybrid"  # hybrid=混合流水线; off=保持占位行为
    VLM_MODEL_NAME: str = "glm-4.1v-flash"  # OCR的VLM兜底模型
    OCR_MIN_CONFIDENCE: float = 0.85  # RapidOCR分支的路由阈值(平均置信度)
```

文件存储配置区把 ALLOWED_EXTENSIONS 默认值改为（移除 `.doc`）：

```python
    ALLOWED_EXTENSIONS: Annotated[list[str], NoDecode] = [".pdf", ".jpg", ".jpeg", ".png", ".docx"]
```

（项目 `.env` 未显式配置 ALLOWED_EXTENSIONS，默认值即生效；README 环境变量表后续 Task 一并更新。）

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ocr/test_config_ocr.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/test_ocr/test_config_ocr.py
git commit -m "feat(ocr): OCR流水线配置项+允许扩展名移除.doc" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: OCRResult + 业务校验纯函数

**Files:**
- Create: `backend/app/ocr/__init__.py`
- Create: `backend/app/ocr/types.py`
- Create: `backend/app/ocr/validators.py`
- Test: `backend/tests/test_ocr/test_validators.py`

- [ ] **Step 1: 写失败测试**

```python
"""
增值税发票业务校验纯函数测试
税号位数 / 勾稽 ±0.01 / 日期 / 发票号一致性
"""
from app.ocr.validators import validate_invoice


GOOD = {
    "invoice_no": "25617000000123456789",
    "date": "2026-08-15",
    "amount_excl": "95.00",
    "tax": "5.00",
    "amount_total": "100.00",
    "buyer_tax_id": "91320100MA1EXAMPLE",   # 18位含字母
    "seller_tax_id": "91320100123456789X",
}


def test_all_pass():
    assert validate_invoice(GOOD) == []


def test_missing_invoice_no():
    fields = {**GOOD, "invoice_no": ""}
    anomalies = validate_invoice(fields)
    assert any("发票号码缺失" in a for a in anomalies)


def test_bad_invoice_no_format():
    fields = {**GOOD, "invoice_no": "12345"}  # 太短
    assert any("发票号码格式异常" in a for a in validate_invoice(fields))


def test_invoice_no_mismatch_with_declared():
    assert any("发票号不一致" in a for a in validate_invoice(GOOD, declared_no="9999999999"))
    # 手填为空不比对
    assert validate_invoice(GOOD, declared_no=None) == []


def test_tax_id_length():
    fields = {**GOOD, "seller_tax_id": "91320100KUNOWN1234"}  # 19位
    assert any("销方税号格式异常" in a for a in validate_invoice(fields))
    # 缺失不报(票面可能无)
    fields = {k: v for k, v in GOOD.items() if k != "buyer_tax_id"}
    assert not any("税号" in a for a in validate_invoice(fields))


def test_amount_reconciliation():
    fields = {**GOOD, "tax": "6.00"}  # 95+6 != 100
    assert any("勾稽不符" in a for a in validate_invoice(fields))
    ok = {**GOOD, "amount_excl": "95.005", "tax": "4.995", "amount_total": "100.00"}
    assert validate_invoice(ok) == []  # ±0.01容差


def test_amounts_missing():
    fields = {k: v for k, v in GOOD.items() if k not in ("amount_excl", "tax")}
    assert any("金额字段缺失" in a for a in validate_invoice(fields))


def test_date_formats():
    assert any("开票日期格式异常" in a for a in validate_invoice({**GOOD, "date": "2026/8/15"}))
    assert validate_invoice({**GOOD, "date": "2026年08月15日"}) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_validators.py -v`
Expected: 收集失败 `ModuleNotFoundError: No module named 'app.ocr'`

- [ ] **Step 3: 实现**

`backend/app/ocr/__init__.py`:

```python
"""
OCR混合流水线包
RapidOCR第一层 → 正则KIE / GLM-VLM → 确定性业务校验
"""
```

`backend/app/ocr/types.py`:

```python
"""
OCR结果数据结构
"""
from dataclasses import dataclass, field


@dataclass
class OCRResult:
    """单张发票的结构化提取结果"""
    method: str = "placeholder"  # rapidocr / vlm / text / placeholder
    raw_text: str = ""           # 提取全文（docx/txt为直读文本）
    confidence: float = 0.0      # RapidOCR平均置信度，其余来源为0
    fields: dict = field(default_factory=dict)      # KIE/VLM抽取的结构化字段
    anomalies: list = field(default_factory=list)   # 业务校验异常描述

    @property
    def ok(self) -> bool:
        """抽取到字段且校验全过"""
        return bool(self.fields) and not self.anomalies
```

`backend/app/ocr/validators.py`:

```python
"""
增值税发票确定性业务校验（纯函数）
税号18/20位数字、不含税+税额=价税合计±0.01、日期合法、发票号与手填一致
"""
from datetime import datetime

TAX_ID_LENGTHS = (18, 20)


def validate_invoice_no(fields: dict, declared_no: str | None) -> list[str]:
    inv = str(fields.get("invoice_no") or "").strip()
    if not inv:
        return ["发票号码缺失"]
    if not inv.isdigit() or not (8 <= len(inv) <= 20):
        return [f"发票号码格式异常: {inv}"]
    declared = (declared_no or "").strip()
    if declared and inv != declared:
        return [f"发票号不一致: 票面{inv} vs 手填{declared}"]
    return []


def validate_tax_ids(fields: dict) -> list[str]:
    anomalies = []
    for side, key in (("购方", "buyer_tax_id"), ("销方", "seller_tax_id")):
        v = str(fields.get(key) or "").strip()
        if not v:
            continue  # 票面可能无，缺失不算异常（由KIE路由层控制完整性）
        if not v.isdigit() or len(v) not in TAX_ID_LENGTHS:
            anomalies.append(f"{side}税号格式异常: {v}")
    return anomalies


def validate_amounts(fields: dict) -> list[str]:
    try:
        excl = float(fields["amount_excl"])
        tax = float(fields["tax"])
        total = float(fields["amount_total"])
    except (KeyError, TypeError, ValueError):
        return ["金额字段缺失或非法，无法勾稽核对"]
    if abs(excl + tax - total) > 0.01:
        return [f"勾稽不符: 不含税{excl} + 税额{tax} != 价税合计{total}"]
    return []


def validate_date(fields: dict) -> list[str]:
    raw = str(fields.get("date") or "").strip()
    if not raw:
        return []
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日"):
        try:
            datetime.strptime(raw, fmt)
            return []
        except ValueError:
            continue
    return [f"开票日期格式异常: {raw}"]


def validate_invoice(fields: dict, declared_no: str | None = None) -> list[str]:
    """全部业务校验，返回异常描述列表（空=全过）"""
    return (
        validate_invoice_no(fields, declared_no)
        + validate_tax_ids(fields)
        + validate_amounts(fields)
        + validate_date(fields)
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ocr/test_validators.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/ocr/__init__.py backend/app/ocr/types.py backend/app/ocr/validators.py backend/tests/test_ocr/test_validators.py
git commit -m "feat(ocr): OCRResult结构与发票业务校验纯函数" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: KIE 正则抽取

**Files:**
- Create: `backend/app/ocr/kie.py`
- Test: `backend/tests/test_ocr/test_kie.py`

- [ ] **Step 1: 写失败测试**

```python
"""
增值税发票字段正则抽取(KIE)纯函数测试
"""
from app.ocr.kie import extract_fields, key_fields_complete

SAMPLE = """江苏增值税电子普通发票
购买方名称：测试科技有限公司  纳税人识别号：91320100MA1EXAMPLE
销售方名称：南京某某商贸有限公司  纳税人识别号：91320100KUNOWN1234
开票日期：2026年08月15日
项目名称 规格 单价 金额 税率 税额
*信息技术服务*平台服务费        ¥95.00    6%  ¥5.00
合 计                        ¥95.00        ¥5.00
价税合计（大写） 壹佰元整      ¥100.00
发票号码：25617000000123456789"""


def test_extract_full_sample():
    fields = extract_fields(SAMPLE)
    assert fields["invoice_no"] == "25617000000123456789"
    assert fields["date"] == "2026年08月15日"
    assert fields["amount_excl"] == "95.00"
    assert fields["tax"] == "5.00"
    assert fields["amount_total"] == "100.00"
    assert fields["buyer_tax_id"] == "91320100MA1EXAMPLE"
    assert fields["seller_tax_id"] == "91320100KUNOWN1234"


def test_extract_dash_date_and_comma_amounts():
    text = "开票日期：2026-08-15\n合 计 ¥1,000.00 ¥60.00\n价税合计（大写）壹仟零陆拾元 ¥1,060.00"
    fields = extract_fields(text)
    assert fields["date"] == "2026-08-15"
    assert fields["amount_excl"] == "1000.00"
    assert fields["amount_total"] == "1060.00"


def test_key_fields_complete():
    assert key_fields_complete({"invoice_no": "1" * 8, "amount_total": "1.00"})
    assert not key_fields_complete({"invoice_no": "1" * 8})          # 缺价税合计
    assert not key_fields_complete(extract_fields("无关文本"))


def test_empty_text():
    assert extract_fields("") == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_kie.py -v`
Expected: 收集失败 `No module named 'app.ocr.kie'`

- [ ] **Step 3: 实现**

`backend/app/ocr/kie.py`:

```python
"""
增值税发票字段正则抽取（KIE, Key Information Extraction）——纯函数
输入RapidOCR/docx直读的全文文本，输出结构化字段dict
票面布局多变，只做保守抽取：匹配不到的字段缺失，由路由层决定是否升级VLM
"""
import re

_RE_INVOICE_NO = re.compile(r"发票号码[:：]?\s*(\d{8,20})")
_RE_DATE = re.compile(
    r"开票日期[:：]?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{1,2}-\d{1,2})"
)
# 合计行：合计 ¥95.00 ¥5.00（不含税金额、税额并排）
_RE_SUBTOTAL = re.compile(
    r"合\s*计\s*[¥￥]?\s*([0-9,]+\.\d{2})\s*[¥￥]?\s*([0-9,]+\.\d{2})"
)
# 价税合计行：价税合计（大写） 壹佰元整 ¥100.00
_RE_TOTAL = re.compile(r"价税合计[^0-9¥￥]{0,20}[¥￥]?\s*([0-9,]+\.\d{2})")
# 税号：购销方各一，按出现顺序取
_RE_TAX_ID = re.compile(r"纳税人识别号[:：]?\s*([0-9A-Z]{15,20})")

# 路由判定的关键字段：齐了才走KIE分支，缺任一升级VLM
KEY_FIELDS = ("invoice_no", "amount_total")


def _clean_amount(s: str) -> str:
    return s.replace(",", "")


def extract_fields(text: str) -> dict:
    """从全文文本抽取发票字段，抽取不到的键缺失"""
    fields: dict = {}
    if m := _RE_INVOICE_NO.search(text):
        fields["invoice_no"] = m.group(1)
    if m := _RE_DATE.search(text):
        fields["date"] = re.sub(r"\s+", "", m.group(1))
    if m := _RE_SUBTOTAL.search(text):
        fields["amount_excl"] = _clean_amount(m.group(1))
        fields["tax"] = _clean_amount(m.group(2))
    if m := _RE_TOTAL.search(text):
        fields["amount_total"] = _clean_amount(m.group(1))
    ids = _RE_TAX_ID.findall(text)
    if len(ids) >= 1:
        fields["buyer_tax_id"] = ids[0]
    if len(ids) >= 2:
        fields["seller_tax_id"] = ids[1]
    return fields


def key_fields_complete(fields: dict) -> bool:
    """路由用：关键字段（发票号+价税合计）是否齐全"""
    return all(fields.get(k) for k in KEY_FIELDS)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ocr/test_kie.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/ocr/kie.py backend/tests/test_ocr/test_kie.py
git commit -m "feat(ocr): 增值税发票正则KIE抽取" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: RapidOCR provider

**Files:**
- Create: `backend/app/ocr/rapidocr_provider.py`
- Test: `backend/tests/test_ocr/test_rapidocr_provider.py`

- [ ] **Step 1: 写失败测试**

```python
"""
RapidOCR封装测试
懒加载引擎可替换；PDF分派；任何异常向上抛（由pipeline降级）
"""
import base64

import pytest

from app.ocr import rapidocr_provider

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _FakeEngine:
    """固定输出：两行文本带不同置信度"""
    def __call__(self, img):
        assert img is not None
        return (
            [
                ([[0, 0], [10, 0], [10, 10], [0, 10]], "发票号码:12345678", 0.9),
                ([[0, 0], [10, 0], [10, 10], [0, 10]], "价税合计 ¥100.00", 0.8),
            ],
            0.1,
        )


def test_run_ocr_image(monkeypatch, tmp_path):
    monkeypatch.setattr(rapidocr_provider, "_get_engine", lambda: _FakeEngine())
    p = tmp_path / "inv.png"
    p.write_bytes(PNG_1PX)
    text, confidence = rapidocr_provider.run_ocr(p)
    assert "发票号码:12345678" in text and "价税合计" in text
    assert confidence == pytest.approx(0.85)  # (0.9+0.8)/2


def test_run_ocr_empty_result(monkeypatch, tmp_path):
    class _Empty:
        def __call__(self, img):
            return None, 0.1
    monkeypatch.setattr(rapidocr_provider, "_get_engine", lambda: _Empty())
    p = tmp_path / "blank.png"
    p.write_bytes(PNG_1PX)
    assert rapidocr_provider.run_ocr(p) == ("", 0.0)


def test_missing_file_raises(tmp_path):
    """文件不存在：异常向上抛（pipeline捕获降级），不静默"""
    with pytest.raises(Exception):
        rapidocr_provider.run_ocr(tmp_path / "nope.png")


@pytest.mark.llm
def test_real_rapidocr_reads_digits(tmp_path):
    """真实引擎：opencv画数字图片应被识别（标记llm默认跳过）"""
    import numpy as np
    import cv2
    img = np.full((80, 400), 255, dtype=np.uint8)
    cv2.putText(img, "12345678", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
    p = tmp_path / "real.png"
    cv2.imwrite(str(p), img)
    text, confidence = rapidocr_provider.run_ocr(p)
    assert "12345678" in text.replace(" ", "")
    assert confidence > 0.5
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_rapidocr_provider.py -v`
Expected: 收集失败 `No module named 'app.ocr.rapidocr_provider'`

- [ ] **Step 3: 实现**

`backend/app/ocr/rapidocr_provider.py`:

```python
"""
RapidOCR封装（rapidocr-onnxruntime）
懒加载单例引擎；PDF经PyMuPDF逐页转图
本层失败直接抛异常——降级决策统一在pipeline做
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_engine = None  # 懒加载单例：模型加载约1s，进程内复用


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _pdf_to_images(path: Path) -> list[bytes]:
    """PDF逐页渲染为PNG字节流（150dpi足够票据OCR）"""
    import pymupdf
    doc = pymupdf.open(path)
    try:
        return [page.get_pixmap(dpi=150).tobytes("png") for page in doc]
    finally:
        doc.close()


def run_ocr(path: str | Path) -> tuple[str, float]:
    """
    图片/PDF → (全文文本, 平均置信度)
    引擎接受路径/bytes；rapidocr-onnxruntime自带方向处理
    """
    p = Path(path)
    pages = _pdf_to_images(p) if p.suffix.lower() == ".pdf" else [p.read_bytes()]
    engine = _get_engine()
    lines: list[str] = []
    scores: list[float] = []
    for img in pages:
        result, _elapse = engine(img)
        for _box, text, score in result or []:
            lines.append(text)
            scores.append(float(score))
    text = "\n".join(lines)
    confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
    return text, confidence
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ocr/test_rapidocr_provider.py -v`
Expected: 3 passed, 1 deselected（llm标记）

- [ ] **Step 5: 提交**

```bash
git add backend/app/ocr/rapidocr_provider.py backend/tests/test_ocr/test_rapidocr_provider.py
git commit -m "feat(ocr): RapidOCR封装(懒加载+PDF转图)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: GLM-VLM provider

**Files:**
- Create: `backend/app/ocr/vlm_provider.py`
- Test: `backend/tests/test_ocr/test_vlm_provider.py`

- [ ] **Step 1: 写失败测试**

```python
"""
GLM-VLM抽取测试
JSON解析(纯/markdown fence/垃圾)；LLM调用mock；失败返回None
"""
from app.ocr import vlm_provider


def test_parse_plain_json():
    assert vlm_provider._parse_json('{"invoice_no": "123"}') == {"invoice_no": "123"}


def test_parse_fenced_json():
    s = '```json\n{"invoice_no": "123", "date": "2026-08-15"}\n```'
    assert vlm_provider._parse_json(s) == {"invoice_no": "123", "date": "2026-08-15"}


def test_parse_garbage_returns_none():
    assert vlm_provider._parse_json("抱歉我无法识别") is None
    assert vlm_provider._parse_json('["not", "dict"]') is None


def test_extract_fields_llm_error(monkeypatch, tmp_path):
    """LLM抛异常 → None（pipeline降级），不外抛"""
    import langchain_openai

    class _Boom:
        def __init__(self, **kw):
            raise RuntimeError("api down")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Boom)
    p = tmp_path / "inv.png"
    p.write_bytes(b"\x89PNG fake")
    assert vlm_provider.extract_fields(p) is None


def test_extract_fields_success(monkeypatch, tmp_path):
    class _Resp:
        content = '{"invoice_no": "25617000000123456789", "amount_total": "100.00"}'

    class _FakeLLM:
        def __init__(self, **kw):
            pass
        def invoke(self, messages):
            assert messages[0].content[0]["type"] == "text"
            assert messages[0].content[1]["type"] == "image_url"
            return _Resp()

    import langchain_openai
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _FakeLLM)
    p = tmp_path / "inv.jpg"
    p.write_bytes(b"\xff\xd8 fake jpeg")
    fields = vlm_provider.extract_fields(p)
    assert fields == {"invoice_no": "25617000000123456789", "amount_total": "100.00"}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_vlm_provider.py -v`
Expected: 收集失败 `No module named 'app.ocr.vlm_provider'`

- [ ] **Step 3: 实现**

`backend/app/ocr/vlm_provider.py`:

```python
"""
GLM视觉模型端到端抽取（复杂票面兜底）
图片base64 → VLM → JSON字段；任何失败返回None（pipeline降级）
"""
import base64
import json
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是发票信息抽取助手。仔细看这张发票图片，提取以下字段，"
    '严格返回JSON对象（不要markdown代码块）：{"invoice_no": "发票号码", '
    '"date": "开票日期(YYYY-MM-DD)", "amount_excl": "不含税金额(数字)", '
    '"tax": "税额(数字)", "amount_total": "价税合计(数字)", '
    '"buyer_tax_id": "购买方纳税人识别号", "seller_tax_id": "销售方纳税人识别号"}。'
    "字段值均为字符串；无法辨认的字段填空字符串，绝不编造。只返回JSON，不要其他文字。"
)


def _image_data_url(path: Path) -> str:
    """本地图片/PDF首页 → data URL（PDF取首页，多页票据极少见）"""
    if path.suffix.lower() == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        try:
            raw = doc[0].get_pixmap(dpi=150).tobytes("png")
            mime = "image/png"
        finally:
            doc.close()
    else:
        raw = path.read_bytes()
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _parse_json(content: str) -> dict | None:
    """容错解析：剥markdown fence；非dict/解析失败返回None"""
    s = content.strip()
    if s.count("```") >= 2:
        s = s.split("```")[1]
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_fields(path: str | Path) -> dict | None:
    """VLM抽取发票字段；失败返回None（调用方降级，不抛异常）"""
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.VLM_MODEL_NAME,
            api_key=settings.GLM_API_KEY,
            base_url=settings.GLM_API_BASE,
            temperature=0,
            max_tokens=1024,
        )
        msg = HumanMessage(content=[
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": _image_data_url(Path(path))}},
        ])
        resp = llm.invoke([msg])
        return _parse_json(resp.content)
    except Exception as e:
        logger.warning(f"VLM抽取失败: {e}")
        return None
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ocr/test_vlm_provider.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/ocr/vlm_provider.py backend/tests/test_ocr/test_vlm_provider.py
git commit -m "feat(ocr): GLM-VLM端到端发票抽取(失败降级None)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: pipeline 编排与路由

**Files:**
- Create: `backend/app/ocr/pipeline.py`
- Test: `backend/tests/test_ocr/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

```python
"""
OCR混合流水线编排测试
路由判定(置信度+关键字段)、降级链、off开关、校验接入
"""
import pytest

from app.config import settings
from app.ocr import pipeline
from app.ocr.types import OCRResult

SAMPLE_TEXT = "发票号码：25617000000123456789\n合 计 ¥95.00 ¥5.00\n价税合计 ¥100.00"
COMPLETE_FIELDS = {
    "invoice_no": "25617000000123456789", "date": "2026-08-15",
    "amount_excl": "95.00", "tax": "5.00", "amount_total": "100.00",
}


@pytest.fixture()
def img(tmp_path):
    p = tmp_path / "inv.png"
    p.write_bytes(b"\x89PNG fake")
    return p


def test_high_confidence_complete_routes_rapidocr(monkeypatch, img):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "hybrid")
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT, 0.95))
    r = pipeline.extract_invoice(img)
    assert r.method == "rapidocr"
    assert r.confidence == 0.95
    assert r.fields["invoice_no"] == "25617000000123456789"
    assert r.anomalies == []  # 样例票勾稽平衡


def test_low_confidence_routes_vlm(monkeypatch, img):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "hybrid")
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT, 0.3))
    monkeypatch.setattr(
        pipeline, "vlm_extract",
        lambda p: {**COMPLETE_FIELDS, "buyer_tax_id": "91320100123456789X"},
    )
    r = pipeline.extract_invoice(img)
    assert r.method == "vlm"
    assert r.fields["amount_total"] == "100.00"
    assert r.anomalies == []


def test_high_confidence_but_kie_incomplete_routes_vlm(monkeypatch, img):
    """置信度够但正则抽不全（缺价税合计行）→ 升级VLM"""
    monkeypatch.setattr(settings, "OCR_PROVIDER", "hybrid")
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: ("模糊票面文本", 0.9))
    monkeypatch.setattr(pipeline, "vlm_extract", lambda p: COMPLETE_FIELDS)
    r = pipeline.extract_invoice(img)
    assert r.method == "vlm"


def test_rapidocr_fails_and_vlm_fails_placeholder(monkeypatch, img):
    def _boom(p):
        raise RuntimeError("engine down")
    monkeypatch.setattr(pipeline, "run_ocr", _boom)
    monkeypatch.setattr(pipeline, "vlm_extract", lambda p: None)
    r = pipeline.extract_invoice(img)
    assert r.method == "placeholder"
    assert r.anomalies == ["OCR与VLM均不可用"]


def test_vlm_fails_low_confidence_keeps_rapidocr_text(monkeypatch, img):
    """低置信OCR出了字+VLM挂 → 保留rapidocr文本，校验补字段缺失异常"""
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT[:20], 0.5))
    monkeypatch.setattr(pipeline, "vlm_extract", lambda p: None)
    r = pipeline.extract_invoice(img)
    assert r.method == "rapidocr"
    assert r.raw_text == SAMPLE_TEXT[:20]
    assert any("缺失" in a or "勾稽" in a for a in r.anomalies)


def test_provider_off(monkeypatch, img):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "off")
    r = pipeline.extract_invoice(img)
    assert r.method == "placeholder"
    assert r.anomalies == ["OCR未启用(OCR_PROVIDER=off)"]


def test_validation_anomalies_attached(monkeypatch, img):
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (
        "发票号码：25617000000123456789\n合 计 ¥95.00 ¥6.00\n价税合计 ¥100.00", 0.95
    ))
    r = pipeline.extract_invoice(img)  # 95+6 != 100
    assert any("勾稽不符" in a for a in r.anomalies)
    assert r.ok is False


def test_declared_no_mismatch(monkeypatch, img):
    monkeypatch.setattr(pipeline, "run_ocr", lambda p: (SAMPLE_TEXT, 0.95))
    r = pipeline.extract_invoice(img, declared_no="999")
    assert any("发票号不一致" in a for a in r.anomalies)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_pipeline.py -v`
Expected: 收集失败 `No module named 'app.ocr.pipeline'`

- [ ] **Step 3: 实现**

`backend/app/ocr/pipeline.py`:

```python
"""
OCR混合流水线编排
RapidOCR第一层 → 路由判定(平均置信度≥阈值 且 KIE关键字段齐全)
  ├─ 是 → KIE正则抽取
  └─ 否 → GLM-VLM端到端抽取
→ 确定性业务校验(validators)
降级链：rapidocr失败→VLM；VLM失败→占位；任何一层失败不影响调用方
"""
import logging
from pathlib import Path

from app.config import settings
from app.ocr import kie, validators
from app.ocr.rapidocr_provider import run_ocr
from app.ocr.types import OCRResult
from app.ocr.vlm_provider import extract_fields as vlm_extract

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def extract_invoice(path: str | Path, declared_no: str | None = None) -> OCRResult:
    """图片/PDF发票 → OCRResult（不抛异常）"""
    if settings.OCR_PROVIDER == "off":
        return OCRResult(anomalies=["OCR未启用(OCR_PROVIDER=off)"])

    text, confidence = "", 0.0
    try:
        text, confidence = run_ocr(path)
    except Exception as e:
        logger.warning(f"RapidOCR失败，降级VLM: {e}")

    # 第一路由：置信度够 → 先试KIE
    fields = kie.extract_fields(text) if confidence >= settings.OCR_MIN_CONFIDENCE else {}
    method = None
    if kie.key_fields_complete(fields):
        method = "rapidocr"
    else:
        # KIE不完整（低置信/字段缺）→ VLM兜底
        vlm_fields = vlm_extract(path)
        if vlm_fields:
            fields, method = vlm_fields, "vlm"
        elif text:
            method = "rapidocr"  # VLM失败但OCR出了字：用KIE部分字段，让校验层报缺失
        else:
            return OCRResult(anomalies=["OCR与VLM均不可用"])

    anomalies = validators.validate_invoice(fields, declared_no)
    return OCRResult(
        method=method,
        raw_text=text,
        confidence=confidence,
        fields=fields,
        anomalies=anomalies,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_ocr/test_pipeline.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/ocr/pipeline.py backend/tests/test_ocr/test_pipeline.py
git commit -m "feat(ocr): 混合流水线编排(置信度路由+逐层降级)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: ocr_tool 重写（接入点）

**Files:**
- Modify: `backend/app/tools/ocr_tool.py`（整文件重写）
- Test: `backend/tests/test_ocr/test_ocr_tool.py`

- [ ] **Step 1: 写失败测试**

```python
"""
ocr_tool接入测试
txt/docx直读+KIE+校验；图片/PDF走pipeline；/uploads相对路径映射；缺失文件空串
"""
import base64

from app.config import settings
from app.tools.ocr_tool import format_ocr_result, read_invoice_ocr, read_invoice_text

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

GOOD_TEXT = (
    "发票号码：25617000000123456789\n"
    "开票日期：2026-08-15\n"
    "合 计 ¥95.00 ¥5.00\n"
    "价税合计（大写）壹佰元整 ¥100.00\n"
)


def _write_docx(path, text):
    from docx import Document
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    doc.save(str(path))


def test_txt_direct_read_with_kie(tmp_path):
    p = tmp_path / "inv.txt"
    p.write_text(GOOD_TEXT, encoding="utf-8")
    r = read_invoice_ocr(str(p))
    assert r.method == "text"
    assert r.fields["invoice_no"] == "25617000000123456789"
    assert r.anomalies == []
    text = read_invoice_text(str(p))
    assert "【抽取字段】" in text and "【校验异常】" not in text


def test_docx_direct_read(tmp_path):
    p = tmp_path / "inv.docx"
    _write_docx(p, GOOD_TEXT)
    r = read_invoice_ocr(str(p))
    assert r.method == "text"  # docx跳过OCR层，同文本直读路径
    assert r.fields["amount_total"] == "100.00"


def test_bad_reconciliation_reports(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text(GOOD_TEXT.replace("¥5.00", "¥6.00"), encoding="utf-8")
    text = read_invoice_text(str(p))
    assert "【校验异常】" in text and "勾稽不符" in text


def test_image_routes_pipeline(tmp_path, monkeypatch):
    from app.ocr import pipeline
    from app.ocr.types import OCRResult
    captured = {}

    def _fake_extract(path, declared_no=None):
        captured["path"] = str(path)
        return OCRResult(method="rapidocr", raw_text="票面文本",
                         confidence=0.9, fields={"invoice_no": "12345678"},
                         anomalies=["勾稽不符: 1+2 != 3"])

    monkeypatch.setattr(pipeline, "extract_invoice", _fake_extract)
    p = tmp_path / "inv.png"
    p.write_bytes(PNG_1PX)
    r = read_invoice_ocr(str(p))
    assert r.method == "rapidocr"
    assert captured["path"] == str(p)
    assert "勾稽不符" in read_invoice_text(str(p))


def test_uploads_url_maps_to_local(tmp_path, monkeypatch):
    """invoice_url 存的是 /uploads/yyyy/mm/x.png 相对路径 → 映射 UPLOAD_DIR"""
    from app.ocr import pipeline
    from app.ocr.types import OCRResult
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        pipeline, "extract_invoice",
        lambda p, declared_no=None: OCRResult(method="rapidocr", raw_text="ok"),
    )
    local = tmp_path / "2026" / "09"
    local.mkdir(parents=True)
    (local / "abc.png").write_bytes(PNG_1PX)
    r = read_invoice_ocr("/uploads/2026/09/abc.png")
    assert r is not None and r.raw_text == "ok"


def test_missing_file_returns_none(tmp_path):
    assert read_invoice_ocr(str(tmp_path / "nope.png")) is None
    assert read_invoice_text(str(tmp_path / "nope.png")) == ""


def test_empty_and_unsupported():
    assert read_invoice_ocr(None) is None
    assert read_invoice_ocr("") is None
    assert read_invoice_text("") == ""


def test_format_ocr_result():
    from app.ocr.types import OCRResult
    r = OCRResult(method="text", raw_text="原文", fields={"invoice_no": "1"},
                  anomalies=["异常A"])
    s = format_ocr_result(r)
    assert s.startswith("原文") and "【抽取字段】" in s and "【校验异常】异常A" in s
    assert format_ocr_result(OCRResult(raw_text="只有原文")) == "只有原文"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_ocr/test_ocr_tool.py -v`
Expected: FAIL `ImportError: cannot import name 'format_ocr_result'`

- [ ] **Step 3: 实现（整文件替换）**

`backend/app/tools/ocr_tool.py`:

```python
"""
OCR工具
发票/单据文本与结构化提取：
- 文本类(.txt/.md/.csv)与.docx：直读文字，跳过OCR层，直接KIE抽取+业务校验
- 图片/PDF：走 app.ocr.pipeline 混合流水线(RapidOCR→KIE/VLM→校验)
- /uploads/* 相对URL映射到本地 UPLOAD_DIR
- http(s)：文本类直读；图片/PDF下载到临时文件后走流水线
read_invoice_text 签名不变（返回拼装文本供DocumentAgent分析）；
read_invoice_ocr 返回结构化 OCRResult（工作流回写用）。
"""
import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import settings
from app.ocr import kie, validators
from app.ocr.types import OCRResult

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def read_invoice_ocr(source: str | None, declared_no: str | None = None) -> OCRResult | None:
    """
    结构化提取发票信息。
    返回 OCRResult；文件缺失/类型不支持/提取失败返回 None（不抛异常）。
    """
    if not source:
        return None
    try:
        if source.startswith(("http://", "https://")):
            return _read_url_ocr(source, declared_no)
        if source.startswith("/uploads/"):
            return _extract_file(
                Path(settings.UPLOAD_DIR) / source[len("/uploads/"):], declared_no
            )
        return _extract_file(Path(source), declared_no)
    except Exception as e:
        logger.warning(f"单据结构化提取失败 [{source}]: {e}")
        return None


def read_invoice_text(source: str | None) -> str:
    """兼容入口（签名不变）：返回「原文+抽取字段+校验异常」拼装文本"""
    r = read_invoice_ocr(source)
    return format_ocr_result(r) if r is not None else ""


def format_ocr_result(r: OCRResult) -> str:
    """OCRResult → 给LLM分析的拼装文本"""
    parts = [r.raw_text]
    if r.fields:
        parts.append("【抽取字段】" + json.dumps(r.fields, ensure_ascii=False))
    if r.anomalies:
        parts.append("【校验异常】" + "；".join(r.anomalies))
    return "\n".join(p for p in parts if p)


# ---------- 内部分派 ----------

def _read_url_ocr(url: str, declared_no: str | None) -> OCRResult | None:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _result_from_text(_download_text(url), declared_no)
    if ext not in IMAGE_EXTENSIONS and ext != ".docx":
        return None
    # 图片/PDF/docx：下载到临时文件走统一分派
    suffix = ext or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(_download_bytes(url))
        tmp = Path(f.name)
    try:
        return _extract_file(tmp, declared_no)
    finally:
        tmp.unlink(missing_ok=True)


def _extract_file(p: Path, declared_no: str | None) -> OCRResult | None:
    if not p.exists():
        logger.warning(f"单据文件不存在: {p}")
        return None
    ext = p.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return _result_from_text(p.read_text(encoding="utf-8", errors="ignore"), declared_no)
    if ext == ".docx":
        return _result_from_text(_read_docx(p), declared_no)
    if ext in IMAGE_EXTENSIONS:
        from app.ocr.pipeline import extract_invoice  # 延迟import避免未装OCR依赖时import失败
        return extract_invoice(p, declared_no)
    return None


def _read_docx(p: Path) -> str:
    from docx import Document
    doc = Document(str(p))
    return "\n".join(par.text for par in doc.paragraphs if par.text.strip())


def _result_from_text(text: str, declared_no: str | None) -> OCRResult:
    """文本直读（txt/docx）：跳过OCR层，直接KIE抽取+业务校验"""
    fields = kie.extract_fields(text)
    return OCRResult(
        method="text",
        raw_text=text,
        fields=fields,
        anomalies=validators.validate_invoice(fields, declared_no),
    )


def _download_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "expense-audit/1.0"})
    with urlopen(req, timeout=10) as resp:  # noqa: S310 白名单场景
        return resp.read().decode("utf-8", errors="ignore")


def _download_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "expense-audit/1.0"})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 白名单场景
        return resp.read()
```

注意 `_extract_file` 里 pipeline 用函数内 import——测试 monkeypatch `app.ocr.pipeline.extract_invoice` 恰好生效（每次调用取模块属性）。

- [ ] **Step 4: 运行确认通过（含 ocr 包全量 + 全局回归）**

Run: `uv run pytest tests/test_ocr/ -v`
Expected: 27 passed, 1 deselected

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/ 2>&1 | tail -2`
Expected: 无新增 FAIL（document_agent 仍走旧 read_invoice_text 新实现，行为兼容）

- [ ] **Step 5: 提交**

```bash
git add backend/app/tools/ocr_tool.py backend/tests/test_ocr/test_ocr_tool.py
git commit -m "feat(ocr): ocr_tool接入混合流水线(txt/docx直读+图片PDF走OCR)" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: DocumentAgent 收集 ocr_items + workflow 回写

**Files:**
- Modify: `backend/app/agents/document_agent.py`
- Modify: `backend/app/agents/workflow.py`（run() 第4步落库处）
- Test: `backend/tests/test_agents/test_document_agent_ocr.py`
- Test: `backend/tests/test_agents/test_ocr_writeback.py`

- [ ] **Step 1: 写失败测试（两个文件）**

`backend/tests/test_agents/test_document_agent_ocr.py`:

```python
"""
DocumentAgent逐明细OCR收集测试
monkeypatch结构化LLM(走确定性兜底)与read_invoice_ocr
"""
import asyncio

from app.agents.document_agent import DocumentAgent
from app.ocr.types import OCRResult
from app.tools import ocr_tool

SNAPSHOT = {
    "expense": {
        "id": 1, "expense_no": "EXP-1", "title": "t", "total_amount": 100.0,
        "status": "submitted",
    },
    "items": [
        {"id": 11, "invoice_url": "/uploads/x.png", "invoice_no": None, "amount": 100.0},
        {"id": 12, "invoice_url": None, "invoice_no": "ABC", "amount": 0.0},
    ],
    "applicant": {"recent_90d_count": 0, "recent_90d_total": 0.0},
}


def test_collects_ocr_items(monkeypatch):
    async def _raise(prompt):
        raise RuntimeError("llm down")
    agent = DocumentAgent()
    monkeypatch.setattr(agent, "structured_chat", _raise)  # 走确定性兜底分支

    def _fake_read(source, declared_no=None):
        if source and "x.png" in source:
            return OCRResult(method="rapidocr", raw_text="票面",
                             fields={"invoice_no": "123"},
                             anomalies=["勾稽不符: 1+2 != 3"])
        return None

    monkeypatch.setattr(ocr_tool, "read_invoice_ocr", _fake_read)

    result = asyncio.run(agent.run({"expense": SNAPSHOT}))
    data = result.data
    # 明细11：OCR有结果
    assert data["ocr_items"][11] == {"verified": False, "anomalies": ["勾稽不符: 1+2 != 3"]}
    # 明细12：无invoice_url不提取
    assert 12 not in data["ocr_items"]
    # 拼装文本进入invoice_texts供LLM分析
    assert "【校验异常】" in data["invoice_texts"]["明细#11"]
```

`backend/tests/test_agents/test_ocr_writeback.py`:

```python
"""
workflow落库回写 expense_items.invoice_verified 测试
FakeGraph固定document输出（含ocr_items），不走真实OCR/LLM
"""
import asyncio

from app.agents import workflow as wf
from app.models import ExpenseItem, ExpenseStatus

from tests.conftest import register_and_login, requires_db

PAYLOAD = {
    "title": "回写测试报销",
    "expense_type": "meal",
    "items": [
        {
            "category_id": 2,
            "description": "工作餐",
            "amount": "50.00",
            "expense_date": "2026-09-01",
            "invoice_no": "INV-WF-WB-001",
        }
    ],
}


class _FakeGraph:
    async def ainvoke(self, state, config=None):
        item_id = state["expense"]["items"][0]["id"]
        return {
            "risk": {"risk_score": 30.0, "risk_level": "low", "factors": []},
            "decision": {"action": "auto_approve", "reason": "低风险", "suggestions": []},
            "rules": {"violations": []},
            "rag": {"relevant_rules": [], "similar_cases": []},
            "document": {
                "invoice_verified": True, "anomalies": [], "summary": "",
                "ocr_items": {item_id: {"verified": True, "anomalies": []}},
            },
            "errors": [],
        }


@requires_db
def test_invoice_verified_writeback(client, db_session, monkeypatch):
    monkeypatch.setattr(wf.workflow, "app", _FakeGraph())
    monkeypatch.setattr(
        wf, "knowledge_base",
        type("K", (), {"add_case_from_expense": staticmethod(lambda *a, **k: None)})(),
    )
    headers = register_and_login(client, "wf_wb1")
    resp = client.post("/api/expenses", json=PAYLOAD, headers=headers)
    expense_id = resp.json()["id"]
    client.post(f"/api/expenses/{expense_id}/submit", headers=headers)

    asyncio.run(wf.workflow.run(db_session, expense_id))

    item = db_session.query(ExpenseItem).one()
    assert item.invoice_verified is True
    assert db_session.get(wf.Expense, expense_id).status == ExpenseStatus.APPROVED
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_agents/test_document_agent_ocr.py tests/test_agents/test_ocr_writeback.py -v`
Expected: 前者 FAIL `KeyError: 'ocr_items'`（data 无该键）；后者 FAIL `assert None is not True`（invoice_verified 未回写，字段默认 False→属性是 False/None 视模型 default，总之不为 True）

- [ ] **Step 3: 实现**

`backend/app/agents/document_agent.py` 顶部 import 区把 `from app.tools.ocr_tool import read_invoice_text` 改为（模块引用——测试通过 monkeypatch `ocr_tool.read_invoice_ocr` 注入假实现，函数内属性访问才能命中补丁）：

```python
from app.tools import ocr_tool
```

`run()` 中发票文本提取段（原 `invoice_texts = {}` 至 for 循环结束）替换为：

```python
        # 1. 发票结构化提取（txt/docx直读+校验；图片/PDF走OCR流水线）
        invoice_texts = {}
        ocr_items = {}
        for it in items:
            if it.get("invoice_url"):
                r = ocr_tool.read_invoice_ocr(
                    it["invoice_url"], declared_no=it.get("invoice_no")
                )
                if r is not None:
                    invoice_texts[f"明细#{it['id']}"] = ocr_tool.format_ocr_result(r)
                    ocr_items[it["id"]] = {"verified": r.ok, "anomalies": r.anomalies}
```

`data = {...}` 字典加一项（`"invoice_texts": invoice_texts,` 之后）：

```python
            "ocr_items": ocr_items,
```

`backend/app/agents/workflow.py` `run()` 第4步落库段：`expense = db.query(Expense)...` 之后、`if action == "auto_approve":` 之前插入：

```python
        # 回写明细发票校验结果（OCR/直读校验全过=True；无发票文件的明细不动）
        ocr_items = final_state.get("document", {}).get("ocr_items") or {}
        for it in expense.items:
            ocr = ocr_items.get(it.id)
            if ocr is not None:
                it.invoice_verified = ocr["verified"]
```

- [ ] **Step 4: 运行确认通过（含回归）**

Run: `TEST_DATABASE_URL=$TESTURL uv run pytest tests/test_agents/ -v`
Expected: 全 passed（含既有 test_workflow_notify），1 deselected

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/document_agent.py backend/app/agents/workflow.py backend/tests/test_agents/test_document_agent_ocr.py backend/tests/test_agents/test_ocr_writeback.py
git commit -m "feat(ocr): 审核工作流回写明细invoice_verified" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: 前端——上传列、预览、代理

**Files:**
- Create: `frontend/src/api/upload.ts`
- Modify: `frontend/src/views/ExpenseSubmitView.vue`
- Modify: `frontend/src/components/ExpenseDetailDrawer.vue`
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: 新建 api/upload.ts**

```typescript
// 发票文件上传 API
import request from '@/utils/request'

export interface UploadResult {
  url: string
  filename: string
  size: number
}

export function uploadInvoice(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  return request.post('/uploads', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
```

- [ ] **Step 2: ExpenseSubmitView.vue 加「发票文件」列**

`<script setup>` import 区加：

```typescript
import type { UploadRequestOptions } from 'element-plus'
import { uploadInvoice } from '@/api/upload'
```

明细行的本地 interface（`amount: number | null` 所在的那个 interface，约31行）加一个可选字段：

```typescript
    invoice_filename?: string
```

`<script setup>` 尾部加：

```typescript
async function handleUpload(row: { invoice_url?: string | null; invoice_filename?: string }, opts: UploadRequestOptions) {
  try {
    const r = await uploadInvoice(opts.file)
    row.invoice_url = r.url
    row.invoice_filename = r.filename
    ElMessage.success(`已上传 ${r.filename}`)
  } catch {
    /* 错误提示由request拦截器统一弹出 */
  }
}
```

模板明细表格「发票号」列之后、「操作」列之前插入：

```vue
          <el-table-column label="发票文件" width="190">
            <template #default="{ row }">
              <el-upload
                :show-file-list="false"
                accept=".pdf,.jpg,.jpeg,.png,.docx"
                :http-request="(opts: UploadRequestOptions) => handleUpload(row, opts)"
              >
                <el-button link type="primary" size="small">
                  <el-icon><Upload /></el-icon>&nbsp;{{ row.invoice_url ? '重新上传' : '上传发票' }}
                </el-button>
              </el-upload>
              <a
                v-if="row.invoice_url"
                :href="row.invoice_url"
                target="_blank"
                class="invoice-link"
              >
                <el-icon><Paperclip /></el-icon>&nbsp;{{ row.invoice_filename || '已上传' }}
              </a>
            </template>
          </el-table-column>
```

样式区追加：

```scss
.invoice-link {
  display: inline-flex;
  align-items: center;
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}
```

（`Upload`/`Paperclip` 图标走全局注册，无需 import。）

- [ ] **Step 3: ExpenseDetailDrawer.vue 发票文件列**

明细表格「发票号」tag 所在列（约175行）之后加一列：

```vue
        <el-table-column label="发票文件" width="120" align="center">
          <template #default="{ row }">
            <template v-if="row.invoice_url">
              <el-image
                v-if="/\.(jpe?g|png)$/i.test(row.invoice_url)"
                :src="row.invoice_url"
                :preview-src-list="[row.invoice_url]"
                preview-teleported
                fit="cover"
                style="width: 44px; height: 44px; border-radius: 4px"
              />
              <a v-else :href="row.invoice_url" target="_blank" class="invoice-dl">下载查看</a>
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
```

样式区追加：

```scss
.invoice-dl {
  color: var(--el-color-primary);
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}
```

- [ ] **Step 4: vite.config.ts 加 /uploads 代理**

proxy 对象加一项：

```typescript
      '/uploads': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
```

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功（vue-tsc 无错）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/upload.ts frontend/src/views/ExpenseSubmitView.vue frontend/src/components/ExpenseDetailDrawer.vue frontend/vite.config.ts
git commit -m "feat(frontend): 明细行发票上传+详情抽屉预览/下载" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: 收尾——全量回归 + README + 环境变量文档

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && TESTURL=$(grep -E "^DATABASE_URL=" ../.env | cut -d= -f2- | sed 's|/agentdb|/expense_db_test|') && TEST_DATABASE_URL="$TESTURL" uv run pytest tests/ -v`
Expected: 全部 passed（约 60 个），1 deselected，无 FAIL

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 更新 README.md 两行（102-103行）**

```
| 📎 Invoice file upload | ✅ Done | `POST /api/uploads` (pdf/jpg/jpeg/png/docx, ≤10MB) → stored under `/uploads/yyyy/mm/`, served as static files |
| 🔍 Real OCR | ✅ Done | Hybrid pipeline: RapidOCR → regex KIE (conf≥0.85 & key fields complete) or GLM-VLM fallback → deterministic validation (tax-ID 18/20 digits, excl+tax=total ±0.01); txt/docx read directly |
```

- [ ] **Step 4: README.zh-CN.md 对应两行同步为中文（102-103行）**

```
| 📎 发票文件上传 | ✅ 已完成 | `POST /api/uploads`（pdf/jpg/jpeg/png/docx，≤10MB）→ 落盘 `/uploads/yyyy/mm/`，静态文件服务 |
| 🔍 真实 OCR | ✅ 已完成 | 混合流水线：RapidOCR → 正则KIE（置信度≥0.85且关键字段齐全）或 GLM-VLM 兜底 → 确定性业务校验（税号18/20位、不含税+税额=价税合计±0.01）；txt/docx 直读 |
```

- [ ] **Step 5: 两份 README 的环境变量表各加三行**（表结构照抄同表已有行；若两份 README 无环境变量表则跳过此步——实施时先 grep `ALLOWED_EXTENSIONS` 确认）

```
| OCR_PROVIDER | hybrid | off 时保持占位行为 |
| VLM_MODEL_NAME | glm-4.1v-flash | OCR 的 VLM 兜底模型 |
| OCR_MIN_CONFIDENCE | 0.85 | RapidOCR 分支的路由阈值 |
```

- [ ] **Step 6: 提交**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: 阶段②完成——发票上传/真实OCR从WIP表移除" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 验收（对照规格阶段②）

1. 提交页每条明细可传 pdf/jpg/png/docx，非法扩展名/超限 400，上传后显示文件名可点开；详情抽屉图片缩略图预览、其余下载链接
2. txt/docx 直读 → KIE 抽取 + 业务校验；图片/PDF 走 RapidOCR（置信度≥0.85 且关键字段齐 → KIE；否则 GLM-VLM）
3. 降级链实测：rapidocr 挂 → VLM；VLM 挂 → 占位；`OCR_PROVIDER=off` → 占位；全程不抛异常
4. 校验异常（勾稽不符/税号位数/发票号不一致）出现在给 DocumentAgent 的文本中；`workflow.run` 落库回写 `expense_items.invoice_verified`
5. `uv run pytest`（约60用例）与 `npm run build` 全绿
