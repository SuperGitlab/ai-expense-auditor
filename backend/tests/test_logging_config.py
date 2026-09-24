"""
日志配置单元测试（无DB）
- AccessLogFilter：/api 访问行去重（由参数日志中间件负责）、非 /api 保留、
  结构异常 fail-open、不误伤应用日志
- ColoredConsoleFormatter：控制台级别名着色，剥离色码后与纯文本一致
- setup_logging：幂等、接管 uvicorn 三件套、文件 handler 创建/禁用/降级
"""
import logging
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

import pytest

from app.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_FORMAT,
    AccessLogFilter,
    ColoredConsoleFormatter,
    WorkerConsoleFormatter,
    setup_logging,
)

# 快照恢复范围：root("")+uvicorn三件套+celery策略logger（本文件用例重配全局日志，不能污染其他用例）
_SNAPSHOT_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "celery.worker.strategy")


@pytest.fixture(autouse=True)
def _restore_logging():
    """快照并恢复各 logger 的 handlers/level/propagate；先 close 新增 handler 释放文件句柄
    （Windows 下不 close 的话 tmp_path 里的日志文件删不掉，pytest 清理会报 PermissionError）"""
    snap = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in _SNAPSHOT_NAMES
    }
    yield
    for name, (handlers, level, propagate) in snap.items():
        lg = logging.getLogger(name)
        for h in lg.handlers:
            if h not in handlers:
                h.close()
        lg.handlers = handlers
        lg.setLevel(level)
        lg.propagate = propagate


def _access_record(status, name="uvicorn.access", method="GET", path="/api/business/x"):
    """按 uvicorn 0.52.4 真实结构构造访问日志 record（5 元组，msg 同源）"""
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", method, path, "1.1", status),
        exc_info=None,
    )


@contextmanager
def _capture_module_warnings(records: list):
    """捕获 app.logging_config 的降级 WARNING。

    不用 caplog：setup_logging 的 dictConfig 会重建 root handlers，
    把 caplog 挂在 root 上的捕获 handler 一并清掉；本模块 logger 不在配置字典中、
    disable_existing_loggers=False，自建 handler 可存活。
    """
    handler = logging.Handler()
    handler.emit = records.append
    lg = logging.getLogger("app.logging_config")
    lg.addHandler(handler)
    try:
        yield records
    finally:
        lg.removeHandler(handler)


# ---------- AccessLogFilter ----------


def test_access_filter_drops_api_lines():
    """/api 访问行去重：参数日志中间件已为同一请求打印更全的一行（含失败），不再重复"""
    f = AccessLogFilter()
    for p in ("/api/expenses", "/api/agent/executions/12",
              "/api/auth/login", "/api/rules/import/document/extract/t?x=1"):
        assert f.filter(_access_record(200, path=p)) is False
        assert f.filter(_access_record(500, path=p)) is False


def test_access_filter_keeps_non_api_lines():
    """非 /api 请求（/uploads 静态资源、/health）不受去重影响，成功失败都保留"""
    f = AccessLogFilter()
    assert f.filter(_access_record(200, path="/uploads/img.png")) is True
    assert f.filter(_access_record(404, path="/uploads/img.png")) is True
    assert f.filter(_access_record(200, path="/health")) is True


def test_access_filter_fail_open_on_unexpected_args():
    """args 结构异常（None/短元组/末位非int如字符串"200"）不抛异常且放行——fail-open"""
    f = AccessLogFilter()
    rec = _access_record(200)
    for bad in (None, ("a", "b"), ("a", "b", "c", "d", "200"), ("a", "b", "c", "d", object())):
        rec.args = bad
        assert f.filter(rec) is True


def test_access_filter_ignores_non_access_logger():
    """filter 挂在 handler 上对全部日志生效：应用日志即使 args 恰为5元组且路径在/api下也不能误伤"""
    assert AccessLogFilter().filter(
        _access_record(200, name="app.api.endpoints.x", path="/api/agent/executions/12")
    ) is True


def test_console_formatter_colors_levelname_only():
    """控制台 formatter 只给级别名上色；剥离色码后与纯文本格式逐字一致"""
    rec = logging.LogRecord(
        name="app.demo", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    colored = ColoredConsoleFormatter(LOG_FORMAT).format(rec)
    plain = logging.Formatter(LOG_FORMAT).format(rec)
    assert "\033[32m" in colored and "\033[0m" in colored
    assert colored.replace("\033[32m", "").replace("\033[0m", "") == plain


def test_console_handler_uses_colored_formatter():
    """setup_logging 后 console handler 挂着色 formatter（文件 handler 用纯文本 formatter）"""
    setup_logging(log_file="")
    consoles = [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler]
    assert len(consoles) == 1
    assert isinstance(consoles[0].formatter, ColoredConsoleFormatter)


def test_worker_formatter_prefixes_child_process_only():
    """worker版formatter：子进程行带「进程名/logger」前缀，MainProcess不加，原record不被污染"""
    child = logging.LogRecord(
        name="celery.app.trace", level=logging.INFO, pathname=__file__, lineno=1,
        msg="Task X[%s] received", args=("id",), exc_info=None,
    )
    child.processName = "ForkPoolWorker-1"
    out = WorkerConsoleFormatter(LOG_FORMAT).format(child)
    assert "ForkPoolWorker-1/celery.app.trace" in out
    assert child.name == "celery.app.trace"  # 格式化后还原，不污染共享record

    main = logging.LogRecord(
        name="app.demo", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hi", args=None, exc_info=None,
    )
    main.processName = "MainProcess"
    main_out = WorkerConsoleFormatter(LOG_FORMAT).format(main)
    assert "- app.demo -" in main_out and "MainProcess" not in main_out


def test_celery_worker_logging_signal_takes_over():
    """celery setup_logging信号处理函数：接管为worker版formatter + strategy去重received"""
    from app.tasks import _worker_logging

    _worker_logging(loglevel=logging.INFO)
    consoles = [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler]
    assert len(consoles) == 1
    assert isinstance(consoles[0].formatter, WorkerConsoleFormatter)
    assert logging.getLogger("celery.worker.strategy").level == logging.WARNING


# ---------- setup_logging ----------


def test_setup_logging_idempotent():
    """重复调用不叠加 handler（console 恰1个、无文件 handler）"""
    setup_logging(log_file="")
    setup_logging(log_file="")
    consoles = [
        h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler
    ]
    assert len(consoles) == 1
    assert not [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]


def test_setup_logging_takes_over_uvicorn_loggers():
    """uvicorn 三件套被接管：清空自带 handler（否则双重输出+200行复活）、改为向 root 传播"""
    setup_logging(log_file="")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        assert lg.handlers == []
        assert lg.propagate is True


def test_setup_logging_creates_file_handler(tmp_path):
    """父目录不存在自动创建；轮转参数正确；日志真的写入文件"""
    log_file = tmp_path / "sub" / "app.log"
    setup_logging(log_file=str(log_file), level="INFO")
    files = [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
    assert len(files) == 1
    assert files[0].maxBytes > 0
    assert files[0].backupCount == LOG_BACKUP_COUNT

    logging.getLogger("app.test_file_write").info("文件通道写入探测")
    files[0].flush()
    assert log_file.exists()
    assert "文件通道写入探测" in log_file.read_text(encoding="utf-8")


def test_setup_logging_file_failure_degrades_to_console(tmp_path):
    """父路径是已存在文件（跨平台触发OSError）→ 无文件handler+console仍在+一条降级WARNING"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    records: list = []
    with _capture_module_warnings(records):
        setup_logging(log_file=str(blocker / "app.log"))
    assert any(
        r.levelno == logging.WARNING and "不可写" in r.getMessage() for r in records
    )
    handlers = logging.getLogger().handlers
    assert not [h for h in handlers if isinstance(h, RotatingFileHandler)]
    assert any(type(h) is logging.StreamHandler for h in handlers)


def test_setup_logging_empty_log_file_disables_file():
    """LOG_FILE 留空=显式禁用文件日志：无文件handler，也不发降级WARNING"""
    records: list = []
    with _capture_module_warnings(records):
        setup_logging(log_file="")
    assert not [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
    assert records == []
