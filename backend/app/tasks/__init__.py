"""
Celery任务队列（broker/result均用Redis）
启动worker：celery -A app.tasks.celery_app worker --loglevel=info（Windows需加 --pool=solo）
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "expense_audit",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)
celery_app.conf.update(
    result_expires=3600,                       # 任务结果保留1小时（观测用）
    timezone="Asia/Shanghai",
    broker_connection_retry_on_startup=True,   # worker启动时broker未就绪自动重试
    task_acks_late=True,                       # 执行完才ack：worker崩溃任务会被重新投递
    worker_prefetch_multiplier=1,              # 单任务跑2-3分钟，拿一个跑一个（公平分发）
)
