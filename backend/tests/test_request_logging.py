"""
请求参数日志中间件单元测试（无DB）
- 脱敏：password/api_key/token 等键值打码后才进日志（项目日志规范铁律6）
- 摘要：JSON解析失败/二进制/超长各有降级展示
- 中间件：JSON body 带脱敏落日志；GET query 可见；轮询成功 GET 静音；非 /api 路径不拦
"""
import asyncio
import logging

from app.middleware import RequestLoggingMiddleware, redact_sensitive, summarize_body


class _Capture:
    """挂到 app.middleware logger 上的记录收集器（不依赖 caplog，自带级别保障）"""

    def __init__(self):
        self.records = []
        self._handler = logging.Handler()
        self._handler.emit = self.records.append
        self._lg = logging.getLogger("app.middleware")

    def __enter__(self):
        self._old_level = self._lg.level
        self._lg.setLevel(logging.INFO)  # 测试环境root可能是默认WARNING，强制放行INFO
        self._lg.addHandler(self._handler)
        return self.records

    def __exit__(self, *exc):
        self._lg.removeHandler(self._handler)
        self._lg.setLevel(self._old_level)
        return False


def _scope(method, path, content_type=None, query=b""):
    headers = [(b"content-type", content_type.encode())] if content_type else []
    return {
        "type": "http", "method": method, "path": path,
        "query_string": query, "headers": headers,
    }


def _drive(scope, body=b""):
    """用最小假ASGI应用驱动中间件一轮：应用侧消费请求体并回200"""
    pending = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    async def app(scope, receive, send):
        while True:
            msg = await receive()
            if msg["type"] == "http.request" and not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(RequestLoggingMiddleware(app)(scope, receive, send))


# ---------- 纯函数 ----------


def test_redact_sensitive_masks_password_and_nested_keys():
    data = {
        "username": "alice", "password": "secret123",
        "profile": {"api_key": "sk-1"}, "tags": ["x", {"token": "t"}],
    }
    out = redact_sensitive(data)
    assert out["username"] == "alice"
    assert out["password"] == "******"
    assert out["profile"]["api_key"] == "******"
    assert out["tags"][1]["token"] == "******"


def test_summarize_body_variants():
    assert summarize_body("application/json", [b'{"a": 1}'], 9) == '{"a": 1}'
    assert summarize_body("multipart/form-data", [b"\x89PNG"], 4) == "(二进制4字节)"
    big = summarize_body("text/plain", [b"x" * 600], 600)
    assert big.startswith("xxx") and "共600字符" in big
    assert summarize_body("", [], 0) == "-"


# ---------- 中间件 ----------


def test_middleware_logs_json_body_with_redaction():
    with _Capture() as records:
        _drive(_scope("POST", "/api/auth/login", "application/json"),
               body=b'{"username":"alice","password":"secret123"}')
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "POST /api/auth/login" in msg
    assert "→ 200" in msg
    assert "alice" in msg and "secret123" not in msg
    assert "******" in msg and "body=" in msg


def test_middleware_logs_query_for_get():
    with _Capture() as records:
        _drive(_scope("GET", "/api/expenses", query=b"status=pending&page=2"))
    msg = records[0].getMessage()
    assert "GET /api/expenses?status=pending&page=2" in msg
    assert "→ 200" in msg


def test_middleware_silent_for_polling_get():
    with _Capture() as records:
        _drive(_scope("GET", "/api/agent/executions/12"))
        _drive(_scope("GET", "/api/notifications/unread-count"))
    assert records == []


def test_middleware_ignores_non_api_paths():
    with _Capture() as records:
        _drive(_scope("GET", "/uploads/img.png"))
    assert records == []
