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
