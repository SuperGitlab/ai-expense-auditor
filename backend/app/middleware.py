"""
业务请求参数日志中间件
uvicorn.access 的访问日志只有「方法 路径 状态码」，看不到请求参数；
这里在每个 /api 请求完成时补一条：方法+路径+query+请求体（脱敏）+状态+耗时。

设计要点：
- 请求体经 receive 旁路缓存（tee），下游应用照常读取，不影响业务
- 敏感字段（password/token/api_key等）打码后才进日志（项目日志规范铁律6）
- 超大请求体只记字节数不攒内存；超长文本截断展示
- 前端轮询接口的成功 GET 维持静音（名单见下方 NOISY_POLLING_PREFIXES）
"""
import json
import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# 前端自动轮询接口（控制台静音名单）：这些 GET 的成功访问行是刷屏源。
# 前端新增轮询接口时在此补一行即可；同前缀的 POST（重试/上传等用户主动操作）不受影响。
NOISY_POLLING_PREFIXES = (
    "/api/notifications/unread-count",      # 顶栏铃铛未读数，30s一次
    "/api/agent/executions/",               # 执行详情画布，3s一次（画布开着才轮询）
    "/api/approvals/pending",               # 审批中心列表，15s一次
    "/api/approvals/running",               # 审批中心列表，15s一次
    "/api/rules/import/document/extract/",  # 规则导入抽取进度，5s一次（对话框开着才轮询）
)

_LOG_BODY_MAX = 500  # 日志里请求体最长展示字符数（防刷屏；完整报文不进日志）
_BUF_CAP = 64 * 1024  # 请求体旁路缓存上限：再大只记总字节数，不逐块攒内存

# 敏感字段名单（键名小写匹配；值一律替换为******）
SENSITIVE_KEYS = {
    "password", "pwd", "old_password", "new_password",
    "token", "access_token", "refresh_token",
    "secret", "api_key", "apikey", "authorization",
}


def redact_sensitive(value):
    """递归打码：dict/list 深入一层层找，命中名单的键值替换为******"""
    if isinstance(value, dict):
        return {
            k: ("******" if str(k).lower() in SENSITIVE_KEYS else redact_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(v) for v in value]
    return value


def summarize_body(content_type: str, chunks: list[bytes], total: int) -> str:
    """请求体 → 日志摘要：JSON解析+脱敏后展示；二进制只记大小；超长截断；空体记-"""
    if total == 0:
        return "-"
    if total > _BUF_CAP:
        return "(请求体%s字节，超出展示上限)" % total
    body = b"".join(chunks)
    if "json" in content_type:
        try:
            parsed = json.loads(body.decode("utf-8"))
            text = json.dumps(redact_sensitive(parsed), ensure_ascii=False)
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = body.decode("utf-8", errors="replace")
    elif content_type.startswith("multipart/") or "octet-stream" in content_type:
        return "(二进制%s字节)" % total
    else:
        text = body.decode("utf-8", errors="replace")
    if len(text) > _LOG_BODY_MAX:
        text = text[:_LOG_BODY_MAX] + "…(共%s字符)" % len(text)
    return text


class RequestLoggingMiddleware:
    """业务请求参数日志：响应完成后一条 INFO（参数脱敏、带状态与耗时）"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        method, path = scope["method"], scope["path"]
        query = scope["query_string"].decode("latin-1")
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        content_type = headers.get("content-type", "")

        chunks: list[bytes] = []
        total = 0
        status: list = [None]

        async def tee_receive() -> Message:
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total <= _BUF_CAP:
                    chunks.append(msg.get("body", b""))
            return msg

        async def tee_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, tee_receive, tee_send)
        finally:
            # 轮询接口的成功GET无参数可看且高频，维持控制台静音（失败仍记录便于排障）
            is_quiet_polling = (
                method == "GET"
                and path.startswith(NOISY_POLLING_PREFIXES)
                and (status[0] or 0) < 400
            )
            if not is_quiet_polling:
                # 一行式：方法 路径?查询 → 状态（耗时）+ 请求体（无则省略）
                full_path = path + ("?" + query if query else "")
                body_summary = summarize_body(content_type, chunks, total)
                body_part = "" if body_summary == "-" else " body=" + body_summary
                logger.info(
                    "业务请求 %s %s → %s（%.1fms）%s",
                    method, full_path, status[0] or "-",
                    (time.perf_counter() - started) * 1000, body_part,
                )
