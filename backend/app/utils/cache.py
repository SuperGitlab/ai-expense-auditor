"""
可选缓存工具
Redis可用时缓存查询结果，不可用时直接透传（优雅降级）
"""
import json
import logging
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

_pool = None
_checked = False


def _get_redis():
    """惰性连接Redis（失败时返回None，仅告警一次）"""
    global _pool, _checked
    if _checked:
        return _pool
    _checked = True
    try:
        import redis
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _pool = client
        logger.info("Redis缓存已连接")
    except Exception as e:
        logger.warning(f"Redis不可用，缓存功能降级: {e}")
    return _pool


def cache_get_or_set(key: str, producer: Callable[[], Any], ttl: int = 60) -> Any:
    """
    缓存读取：命中返回缓存；未命中执行producer并写缓存
    Redis不可用时直接执行producer（不影响功能）

    Args:
        key: 缓存键
        producer: 生产数据的函数
        ttl: 过期秒数
    """
    client = _get_redis()
    if client is None:
        return producer()

    try:
        cached = client.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    value = producer()
    try:
        client.setex(key, ttl, json.dumps(value, default=str))
    except Exception as e:
        logger.debug(f"缓存写入失败: {e}")
    return value
