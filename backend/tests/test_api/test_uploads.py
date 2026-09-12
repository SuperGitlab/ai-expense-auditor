"""
上传接口测试
扩展名/大小校验、落盘、未登录401；/ocr变体：OCR识别回填+降级
"""
import base64

from app.config import settings
from app.models import Category

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


# ---------- /api/uploads/ocr：上传+RapidOCR识别回填 ----------

OCR_MEAL_TEXT = """福建增值税电子普通发票
No 01096036
开票日期：2026年09月01日
*餐饮服务*工作餐
价税合计（大写）贰佰元整
¥200.00"""


@requires_db
def test_upload_ocr_ok(client, db_session, tmp_path, monkeypatch):
    from app.ocr import rapidocr_provider
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(rapidocr_provider, "run_ocr", lambda p: (OCR_MEAL_TEXT, 0.97))
    headers = register_and_login(client, "up_o1")
    resp = client.post(
        "/api/uploads/ocr", files={"file": ("inv.png", PNG_1PX, "image/png")}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"].startswith("/uploads/") and body["filename"] == "inv.png"
    f = body["fields"]
    assert f["发票号"] == "01096036"
    assert f["费用日期"] == "2026-09-01"
    assert f["金额(元)"] == "200.00"
    assert f["费用说明"] == "工作餐"
    assert f["费用类别"] == "餐饮费"
    # 类别名能匹配种子类别 → 返回category_id供下拉框直选
    meal = db_session.query(Category).filter(Category.code == "meal").one()
    assert f["category_id"] == meal.id


@requires_db
def test_upload_ocr_degrades_on_failure(client, db_session, tmp_path, monkeypatch):
    from app.ocr import rapidocr_provider

    def _boom(p):
        raise RuntimeError("ocr down")

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(rapidocr_provider, "run_ocr", _boom)
    headers = register_and_login(client, "up_o2")
    resp = client.post(
        "/api/uploads/ocr", files={"file": ("inv.png", PNG_1PX, "image/png")}, headers=headers
    )
    assert resp.status_code == 201, resp.text  # OCR失败不影响上传本身
    body = resp.json()
    assert body["fields"] is None and body["url"].startswith("/uploads/")


@requires_db
def test_upload_ocr_requires_auth(client):
    resp = client.post("/api/uploads/ocr", files={"file": ("a.png", PNG_1PX, "image/png")})
    assert resp.status_code == 401


@requires_db
def test_upload_ocr_bad_extension(client, db_session, monkeypatch):
    import tempfile
    monkeypatch.setattr(settings, "UPLOAD_DIR", tempfile.mkdtemp())
    headers = register_and_login(client, "up_o3")
    resp = client.post(
        "/api/uploads/ocr",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")}, headers=headers,
    )
    assert resp.status_code == 400
