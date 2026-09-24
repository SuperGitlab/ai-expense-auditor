"""
日志初始化：控制台 + 轮转文件双通道
- 控制台：沿用原 basicConfig 格式（级别名着色）；/api 访问行由参数日志中间件
  （app.middleware）负责打印，此处对 uvicorn.access 去重不重复输出；非 /api 照常
- 文件：LOG_FILE 保存完整日志（含全部访问日志），RotatingFileHandler 10MB×5 轮转，
  打开失败降级为仅控制台（日志配置绝不能阻止服务启动）
- 仅 web 端使用（app.main import 时调用）；Celery worker 不 import main，日志由 celery 自管
"""
import logging
import logging.config
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

try:  # 旧版Windows控制台需显式启用ANSI色彩；无colorama环境静默跳过（仅失去着色）
    import colorama

    colorama.just_fix_windows_console()
except (ImportError, AttributeError):
    pass

# 与原 main.py basicConfig 的格式保持一致（时间 - logger - 级别 - 消息）
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 单文件上限 10MB
LOG_BACKUP_COUNT = 5  # 最多保留 5 个轮转旧文件

# 追踪已挂载的文件 handler：setup_logging 重复调用时先关闭旧句柄（Windows 必需）
_file_handler: RotatingFileHandler | None = None


class ColoredConsoleFormatter(logging.Formatter):
    """
    控制台专用 formatter：只给级别名上色（INFO绿/WARNING黄/ERROR红/DEBUG青），
    便于肉眼快速区分正常流与异常流。仅挂在 console handler 上，
    文件通道仍用纯文本 formatter，色码绝不落盘。
    """

    _COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35;1m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = self._COLORS.get(record.levelname)
        if color:
            # 只替换第一处" - 级别名 - "（即头部级别位，asctime在最前，消息里的同串不受影响）
            header = " - %s - " % record.levelname
            if header in text:
                text = text.replace(
                    header, " - %s%s%s - " % (color, record.levelname, self._RESET), 1
                )
        return text


class WorkerConsoleFormatter(ColoredConsoleFormatter):
    """
    worker版控制台 formatter：prefork子进程（ForkPoolWorker-*）打日志时在logger名前
    带上进程名（并发任务分清是谁打的）；MainProcess不加（dev线程池/主进程下零噪音）。
    仅worker进程使用（app.tasks的setup_logging信号挂载），web端仍用ColoredConsoleFormatter。
    """

    def format(self, record: logging.LogRecord) -> str:
        original_name = record.name
        if record.processName and record.processName != "MainProcess":
            record.name = "%s/%s" % (record.processName, record.name)
        try:
            return super().format(record)
        finally:
            record.name = original_name  # LogRecord可能被多个handler共用，格式化后还原


class AccessLogFilter(logging.Filter):
    """
    控制台访问行去重：/api/* 每个请求已由参数日志中间件（app.middleware）打印一条
    带 query/请求体/状态/耗时的完整日志，uvicorn.access 的同请求行不再重复输出；
    非 /api 请求（/uploads 静态资源、/health 等）保留原样（量小，成功失败都打）。

    uvicorn 0.52.4 访问日志 record.args 为 5 元组
    (client_addr, method, full_path, http_version, status_code)，path 在 args[2]。
    挂在 console handler 上（而非 logger 上），文件通道不受影响——
    LOG_FILE 里仍是完整访问日志（含 /api 与非 /api 的所有访问行）。
    结构不符（websocket / 未来版本变化）一律放行（fail-open），过滤器绝不抛异常。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) >= 5
            and isinstance(args[2], str)
            and args[2].startswith("/api/")
        ):
            return False
        return True


def _make_file_handler(log_file: str) -> RotatingFileHandler | None:
    """创建轮转文件 handler；LOG_FILE 空串=禁用；路径不可写返回 None（降级仅控制台）。"""
    if not log_file or not log_file.strip():
        return None
    path = Path(log_file).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 探测性打开：把只读卷/权限问题暴露在启动瞬间，而不是首条日志时的 Logging error
        with path.open("a", encoding="utf-8"):
            pass
        return RotatingFileHandler(
            path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None


def setup_logging(level: str | None = None, log_file: str | None = None) -> None:
    """
    统一日志入口（app.main import 时调用；level/log_file 传参仅供测试覆盖）。

    幂等：dictConfig 对声明了 handlers 键的 logger 先清空再挂载，重复调用不叠加 handler。
    """
    global _file_handler
    # 沿用原 basicConfig 的容错：非法级别名回退 INFO
    level_name = (level or settings.LOG_LEVEL or "INFO").upper()
    if not isinstance(getattr(logging, level_name, None), int):
        level_name = "INFO"
    resolved = settings.LOG_FILE if log_file is None else log_file

    logging.config.dictConfig(
        {
            "version": 1,
            # 必须 False：否则先于本配置创建、且未在下方点名的 logger 被静默禁用
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {"format": LOG_FORMAT},
                # 控制台专用着色 formatter（级别名上色）；文件通道仍用 standard 纯文本
                "colored": {"()": f"{__name__}.ColoredConsoleFormatter", "format": LOG_FORMAT},
            },
            "filters": {"access_dedup": {"()": f"{__name__}.AccessLogFilter"}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "colored",
                    "stream": "ext://sys.stderr",
                    # 仅控制台去重；文件通道保留完整访问日志
                    "filters": ["access_dedup"],
                },
            },
            "loggers": {
                # 三个都显式 handlers=[]：清掉 uvicorn 默认 handler（其 propagate=False 且自带输出）。
                # 只改 propagate 不清空 → 双重输出，且 200 行绕过 console handler 的 filter 原样复活
                "uvicorn": {"handlers": [], "level": "INFO", "propagate": True},
                "uvicorn.error": {"handlers": [], "level": "INFO", "propagate": True},
                "uvicorn.access": {"handlers": [], "level": "INFO", "propagate": True},
            },
            "root": {"handlers": ["console"], "level": level_name},
        }
    )

    # 文件 handler 走两阶段：不放进 dictConfig——文件打开失败会让整个 dictConfig 抛异常，
    # 而降级语义要求"文件不可写时控制台日志照常工作"
    if _file_handler is not None:
        _file_handler.close()
        logging.getLogger().removeHandler(_file_handler)
        _file_handler = None
    handler = _make_file_handler(resolved)
    if handler is not None:
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logging.getLogger().addHandler(handler)
        _file_handler = handler
    elif resolved and resolved.strip():
        logging.getLogger(__name__).warning(
            "日志文件不可写，已降级为仅控制台输出: %s", resolved
        )
