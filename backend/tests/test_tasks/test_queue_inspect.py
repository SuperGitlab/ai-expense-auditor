"""
队列探查单测：FakeRedis离线跑，不起broker
LPUSH/BRPOP语义：列表[0]=最新入队、[-1]=下一个执行 → ahead=右侧同任务消息数+unacked领取数
消息体对齐kombu真实格式：body=base64([args, kwargs, embed])三元列表；
unacked值=[消息体, exchange, routing_key]（曾因假body只造两元素导致线上全报missing，测试没拦住）
"""
import base64
import json

import redis as redis_lib

from app.tasks.queue_inspect import review_queue_status


def _msg(expense_id: int = 13, task: str = "review.run_ai_review") -> str:
    """构造kombu消息JSON串：headers.task + base64编码的[args, kwargs, embed]三元body"""
    body = base64.b64encode(json.dumps([[expense_id], {}, {"callbacks": None}]).encode()).decode()
    return json.dumps({"headers": {"task": task}, "body": body})


def _unacked_value(expense_id: int) -> str:
    """构造unacked哈希值：JSON [消息体, exchange, routing_key]"""
    return json.dumps([json.loads(_msg(expense_id)), "", "celery"])


class _FakeRedis:
    def __init__(self, messages: list[str], unacked_values: list[str] | None = None):
        self.messages = messages
        self.unacked_values = unacked_values or []

    def lrange(self, key, start, end):
        return self.messages

    def hvals(self, key):
        return self.unacked_values


def _patch(monkeypatch, messages, unacked_values=None):
    fake = _FakeRedis(messages, unacked_values)
    monkeypatch.setattr(redis_lib.Redis, "from_url", lambda url, **kw: fake)


def test_queued_position_right_side_plus_executing(monkeypatch):
    """[0]=最新入队：执行顺序4→3→5；#3前面=1单+1领取中=2；#4下一个就轮到"""
    _patch(monkeypatch, [_msg(5), _msg(3), _msg(4)], [_unacked_value(2)])
    assert review_queue_status(3) == {"state": "queued", "ahead": 2}
    assert review_queue_status(4) == {"state": "queued", "ahead": 1}
    assert review_queue_status(5) == {"state": "queued", "ahead": 3}


def test_duplicate_takes_first_to_execute(monkeypatch):
    """重复消息（重派场景）按最先执行的一条算：ahead不含自己"""
    _patch(monkeypatch, [_msg(3), _msg(3)])
    assert review_queue_status(3) == {"state": "queued", "ahead": 0}


def test_ignores_other_tasks(monkeypatch):
    """非review任务的消息不占排队位（unacked里也不算执行数）"""
    other = json.dumps([json.loads(_msg(7, task="other.task")), "", "celery"])
    _patch(monkeypatch, [_msg(task="other.task"), _msg(3)], [other])
    assert review_queue_status(3) == {"state": "queued", "ahead": 0}


def test_executing_when_claimed_by_worker(monkeypatch):
    """消息被worker领取进unacked→executing（即使队列里还留着重投副本，领取态优先）"""
    _patch(monkeypatch, [_msg(13)], [_unacked_value(13)])
    assert review_queue_status(13) == {"state": "executing"}


def test_malformed_unacked_entry_ignored(monkeypatch):
    """unacked里混入解不开的脏值不拖挂探查、不占执行位"""
    _patch(monkeypatch, [_msg(3)], ["not-json", json.dumps(["garbage"])])
    assert review_queue_status(3) == {"state": "queued", "ahead": 0}


def test_missing_when_not_in_queue(monkeypatch):
    """未开跑、不在队列也未被领取→missing（画布提示可能丢失可重跑）"""
    _patch(monkeypatch, [_msg(9)], [_unacked_value(8)])
    assert review_queue_status(13) == {"state": "missing"}


def test_unknown_on_broker_error(monkeypatch):
    """broker不可达→unknown（探查异常绝不能拖挂轨迹接口）"""

    def _boom(url, **kw):
        raise ConnectionError("broker down")

    monkeypatch.setattr(redis_lib.Redis, "from_url", _boom)
    assert review_queue_status(13) == {"state": "unknown"}
