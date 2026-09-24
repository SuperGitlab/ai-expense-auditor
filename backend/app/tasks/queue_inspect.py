"""
Celery队列只读探查：画布"排队可见性"数据源
区分四态：queued(排队中,ahead=前面还有几单) / executing(已被worker领取未ack) /
         missing(不在队列也未被领取,消息可能随broker重启丢失) / unknown(探查失败)
Redis transport语义：生产者LPUSH进'celery'列表、worker BRPOP从右端取出 →
列表[0]=最新入队、列表[-1]=下一个执行；某单前面的任务数=其右侧同任务消息数+unacked领取数
unacked哈希：acks_late下worker已领取未确认的消息，值=[消息体, exchange, routing_key]
任何异常只降级为unknown：探查绝不能拖挂轨迹接口
"""
import base64
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

REVIEW_TASK = "review.run_ai_review"


def _decode_expense_id(message: str | dict) -> int | None:
    """解析kombu消息（dict或其JSON串）：仅review任务且body可解码时返回args[0]，否则None"""
    try:
        msg = json.loads(message) if isinstance(message, str) else message
        if msg.get("headers", {}).get("task") != REVIEW_TASK:
            return None
        payload = json.loads(base64.b64decode(msg["body"]))  # [args, kwargs, embed]三元列表
        return int(payload[0][0])
    except Exception:
        return None


def _claimed_expense_id(value: str) -> int | None:
    """解析unacked哈希值：JSON [消息体, exchange, routing_key] → 消息体里的报销单id"""
    try:
        return _decode_expense_id(json.loads(value)[0])
    except Exception:
        return None


def inflight_expense_ids() -> set[int] | None:
    """队列+unacked中全部review任务的报销单id（在途集合）；broker不可达等异常返回None

    用途：worker启动自愈扫描的去重依据（多worker并发启动时，已在途的单不再重复派发）。
    """
    import redis

    try:
        r = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
        return {
            eid for eid in (_decode_expense_id(m) for m in r.lrange("celery", 0, -1))
            if eid is not None
        } | {
            eid for eid in (_claimed_expense_id(v) for v in r.hvals("unacked"))
            if eid is not None
        }
    except Exception as e:
        logger.warning("在途任务查询失败: %s", e)
        return None


def review_queue_status(expense_id: int) -> dict:
    """
    只读探查某报销单审核任务的队列状态：
    {"state": "queued", "ahead": N}  排队中，前面还有N单（含已被领取的）
    {"state": "executing"}           已被worker领取（正在执行或预载中，尚未落第一条节点轨迹）
    {"state": "missing"}             未开跑、不在队列也未被领取（消息可能丢失，可重跑/等自愈）
    {"state": "unknown"}             broker不可达等探查失败（画布不显示提示）
    """
    import redis

    try:
        r = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
        queued = [
            eid for eid in (_decode_expense_id(m) for m in r.lrange("celery", 0, -1))
            if eid is not None
        ]
        claiming = {
            eid for eid in (_claimed_expense_id(v) for v in r.hvals("unacked"))
            if eid is not None
        }
    except Exception as e:
        logger.warning("队列探查失败（画布降级为不显示排队提示）: 报销单#%s, err=%s", expense_id, e)
        return {"state": "unknown"}

    # 已被领取优先判定（重投场景可能队列里还有副本，但worker手里的那条才是正在生效的）
    if expense_id in claiming:
        return {"state": "executing"}
    if expense_id not in queued:
        return {"state": "missing"}
    # 重复消息（重派）按最先执行的一条算=最靠右；其右侧的都是排在前面的
    idx = len(queued) - 1 - queued[::-1].index(expense_id)
    ahead = (len(queued) - 1 - idx) + len(claiming)
    return {"state": "queued", "ahead": ahead}
