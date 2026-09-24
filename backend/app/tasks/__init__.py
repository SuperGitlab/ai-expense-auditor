"""
Celery任务队列（broker/result均用Redis）
启动worker：celery -A app.tasks.celery_app worker --loglevel=info（Windows需加 --pool=solo）
"""
import logging

from celery import Celery
from celery.signals import setup_logging as _celery_setup_logging

from app.config import settings

celery_app = Celery(
    "expense_audit",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # worker进程只加载本包，必须显式include任务模块：
    # 否则任务不注册，收到的消息按unregistered丢弃，单据永远卡SUBMITTED
    include=["app.tasks.review", "app.tasks.rule_extraction"],
)
celery_app.conf.update(
    result_expires=3600,                       # 任务结果保留1小时（观测用）
    timezone="Asia/Shanghai",
    broker_connection_retry_on_startup=True,   # worker启动时broker未就绪自动重试
    task_acks_late=True,                       # 执行完才ack：worker崩溃任务会被重新投递
    worker_prefetch_multiplier=1,              # 单任务跑2-3分钟，拿一个跑一个（公平分发）
)


# ---------- worker日志统一：与web同一套控制台格式/配色 ----------
# celery默认自管日志（[时间: 级别/进程] 消息），与web端格式不一致、每个任务还打两行received；
# 接管为app.logging_config的同款格式（级别名着色、子进程带进程名前缀）。
# 文件通道刻意不挂：多进程写同一LOG_FILE会轮转竞争，worker落盘请用celery -f单独给文件。
@_celery_setup_logging.connect
def _worker_logging(loglevel=None, **kwargs):
    """celery setup_logging信号：worker启动时以应用日志配置替换celery默认配置（仅worker进程触发）"""
    from app.logging_config import (
        LOG_FORMAT,
        WorkerConsoleFormatter,
        setup_logging as _setup,
    )

    level = logging.getLevelName(loglevel) if isinstance(loglevel, int) else None
    _setup(level=level, log_file="")
    for h in logging.getLogger().handlers:
        if type(h) is logging.StreamHandler:
            h.setFormatter(WorkerConsoleFormatter(LOG_FORMAT))
    # 去重received：主进程strategy的「Received task:」与子进程trace的「Task ... received」
    # 二选一，保留子进程那行（带执行进程上下文，且与succeeded同一来源）
    logging.getLogger("celery.worker.strategy").setLevel(logging.WARNING)
