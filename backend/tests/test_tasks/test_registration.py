"""
Celery 任务注册测试
回归背景：worker 启动只加载 app.tasks 包，review.py 从未被 import，
run_ai_review 未注册 → worker 收到任务按 unregistered 丢弃 → 单据永远卡 SUBMITTED。
测试全部直接函数调用绕过 broker，故必须显式锁住 include 配置。
"""
import importlib


def test_worker_include_loads_task_module():
    """worker 必须显式 include 任务模块，否则任务不注册、消息被丢弃"""
    from app.tasks import celery_app

    assert "app.tasks.review" in (celery_app.conf.include or ()), (
        "celery_app 未配置 include=['app.tasks.review']，"
        "worker 进程不会加载任务模块，收到的任务会按 unregistered 丢弃"
    )

    module = importlib.import_module("app.tasks.review")
    assert module.run_ai_review.name == "review.run_ai_review"
