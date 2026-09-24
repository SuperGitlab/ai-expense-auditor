"""
Celery队列只读探查脚本：把Redis里Celery的底层数据格式原样看清楚（教学/排查用）

看什么（全程只读：LLEN/LRANGE/HGETALL/SCAN，不动队列任何数据，可随时执行）：
  1. broker库里与Celery相关的key全家福（celery/unacked/unacked_index/_kombu.binding.*）
  2. 'celery'列表每条消息的三层结构，逐步解码：
       ① 外层信封JSON（headers/properties，kombu写的）
       ② body字段的base64串
       ③ 解开后的 [args, kwargs, embed] 三元列表（Celery写的任务载荷）
  3. 'unacked'哈希：worker已领取未确认的消息备份，值=[消息体, exchange, routing_key]
  4. 'unacked_index'哈希：delivery_tag → 队列名（worker崩溃后按此把消息放回原队列）
  5. --results：附带看结果后端 celery-task-meta-* 的任务结果JSON格式

用法（backend/ 目录下）：
    uv run python scripts/inspect_celery.py               # 概览 + 队列前3条逐步解码
    uv run python scripts/inspect_celery.py --limit 10    # 队列多看几条
    uv run python scripts/inspect_celery.py --results     # 附带看任务结果格式

想看到队列里有数据（任选其一）：
  A. 零成本：停掉worker → celery shell里send_task一条假任务 → 本脚本观看 → purge清掉
  B. 真实流：跑 scripts/bulk_submit.py 提交几张单（worker停着不消费）→ 观看 → 起worker
  C. 看unacked有值：worker正在跑审核时（单张2-3分钟）立刻执行本脚本
"""
import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# 将 backend/ 加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis  # noqa: E402  celery[redis]自带，无需单独安装

from app.config import settings  # noqa: E402

QUEUE_KEY = "celery"


def mask_url(url: str) -> str:
    """redis://:pass@host/db → redis://:******@host/db（防止密码打到终端/截图）"""
    parts = urlsplit(url)
    if not parts.password:
        return url
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, f"{parts.username}:******@{host}{port}", parts.path, "", ""))


def show_key_overview(r: "redis.Redis") -> None:
    """broker库里全部key概览：名字/类型/长度——认识Celery在Redis里的'全家福'"""
    print("=" * 72)
    print(f"① broker概况  {mask_url(settings.CELERY_BROKER_URL)}")
    print("=" * 72)
    keys = sorted(r.scan_iter(match="*", count=200))
    if not keys:
        print("（空库：还没有任何Celery数据，先按脚本头部说明造一条消息）")
        return
    for key in keys:
        key_type = r.type(key)
        if key_type == "list":
            size = f"len={r.llen(key)}"
        elif key_type == "hash":
            size = f"len={r.hlen(key)}"
        elif key_type == "zset":
            size = f"len={r.zcard(key)}"
        elif key_type == "set":
            size = f"len={r.scard(key)}"
        else:
            size = key_type
        print(f"  {key:<28} {key_type:<6} {size}")
    print()


def show_queue_messages(r: "redis.Redis", limit: int) -> None:
    """逐条解剖'celery'列表里的消息：信封JSON → base64 → [args, kwargs, embed]"""
    messages = r.lrange(QUEUE_KEY, 0, -1)
    total = len(messages)
    print("=" * 72)
    print(f"② 队列 '{QUEUE_KEY}' 共 {total} 条消息（LPUSH左进 / BRPOP右出 = 先进先出）")
    print("=" * 72)
    if not total:
        print("（队列空：worker没在跑时提交一张报销单，消息就会停留在这里）\n")
        return

    # 按执行先后排序展示：lrange[0]=最新入队(最后执行)，[-1]=下一个被执行(最早入队)
    shown = min(limit, total)
    print(f"按执行顺序展示前 {shown} 条（列表索引[-1]=第1个被worker取走，[0]=最新入队）\n")
    for order, raw in enumerate(reversed(messages), start=1):
        list_idx = total - order  # 该消息在Redis列表里的真实索引
        env = _parse_or_skip(raw)
        if env is None:
            continue
        print(f"----- 第{order}个执行（列表索引[{list_idx}]，共{total}条） -----")

        # ① 外层信封：body太长截断，其余字段原样展示
        display = dict(env)
        body = display.get("body", "")
        if len(body) > 48:
            display["body"] = body[:48] + f"...(base64共{len(body)}字符,下方单独解码)"
        print("① 外层信封JSON（kombu打包，headers.task=任务名）：")
        print(json.dumps(display, indent=2, ensure_ascii=False))

        # ②+③ body两层解码：base64串 → JSON文本 → 三元列表
        try:
            raw_bytes = base64.b64decode(body)
            payload = json.loads(raw_bytes)
        except Exception as e:  # 非JSON序列化器（如pickle）或残缺消息：如实报告不中断
            print(f"   body解码失败（可能非json序列化器）: {e}\n")
            continue
        print(f"② body解码第1步 base64.b64decode → {raw_bytes[:120].decode('utf-8', 'replace')}"
              f"{'...' if len(raw_bytes) > 120 else ''}")
        print("③ body解码第2步 json.loads → [args, kwargs, embed] 三元列表：")
        args, kwargs, embed = payload[0], payload[1], payload[2]
        print(f"    args   = {json.dumps(args, ensure_ascii=False)}   ← 位置参数，args[0]即报销单id")
        print(f"    kwargs = {json.dumps(kwargs, ensure_ascii=False)}")
        print(f"    embed  = {json.dumps(embed, ensure_ascii=False)}   ← chain/chord等工作流，本项目不用\n")


def show_unacked(r: "redis.Redis") -> None:
    """unacked哈希：acks_late下worker已领取未确认的备份；unacked_index：崩溃重投索引"""
    print("=" * 72)
    print("③④ unacked / unacked_index（worker已领取、尚未ack的消息）")
    print("=" * 72)
    unacked = r.hgetall("unacked")  # decode_responses=True → {delivery_tag: JSON串}
    if not unacked:
        print("（空：当前没有正在执行中的任务。worker跑审核的2-3分钟内来查才有值）\n")
        return
    for tag, value in unacked.items():
        print(f"delivery_tag = {tag[:24]}...")
        try:
            backup = json.loads(value)  # [消息体(dict), exchange(str), routing_key(str)]
        except Exception as e:
            print(f"  值解析失败: {e}\n  原文: {value[:200]}\n")
            continue
        msg, exchange, routing_key = backup[0], backup[1], backup[2]
        headers = msg.get("headers", {})
        print(f"  备份值 = [消息体, exchange={exchange!r}, routing_key={routing_key!r}]")
        print(f"  消息体.headers.task = {headers.get('task')}")
        print(f"  消息体.headers.id   = {headers.get('id')}   ← 这次执行的taskId")
        body = msg.get("body", "")
        try:
            payload = json.loads(base64.b64decode(body))
            print(f"  消息体.body解码后 args = {json.dumps(payload[0], ensure_ascii=False)}\n")
        except Exception as e:
            print(f"  消息体.body解码失败: {e}\n")

    # unacked_index实际是zset（首版误当hash读触发WRONGTYPE）：
    # member=delivery_tag、score=领取时刻的unix时间戳，worker崩溃恢复时按时间序放回队列
    index_type = r.type("unacked_index")
    if not index_type:
        print("（没有unacked_index：正常，它与unacked同生同灭）\n")
        return
    print(f"unacked_index（type={index_type}，member=delivery_tag / score=领取时刻）：")
    if index_type == "zset":
        for tag, ts in r.zrange("unacked_index", 0, -1, withscores=True):
            claimed_at = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {tag[:24]}... 领取于 {claimed_at}")
    else:  # 兜底：其他类型只打印类型，不再盲发命令
        print(f"  （非zset类型 {index_type}，跳过详情展示）")
    print()


def show_results(limit: int) -> None:
    """结果后端（--results）：celery-task-meta-<taskId> 每个存一份执行结果JSON"""
    print("=" * 72)
    print(f"⑤ 结果后端  {mask_url(settings.CELERY_RESULT_BACKEND)}")
    print("=" * 72)
    r = redis.Redis.from_url(settings.CELERY_RESULT_BACKEND, decode_responses=True)
    metas = list(r.scan_iter(match="celery-task-meta-*", count=100))[:limit]
    if not metas:
        print("（没有历史结果：任务成功执行后才会写入；result_expires=1小时自动过期）\n")
        return
    for key in metas:
        raw = r.get(key)
        print(f"{key}")
        try:
            print(json.dumps(json.loads(raw), indent=2, ensure_ascii=False))
        except Exception:
            print(f"  {raw[:300]}")
        print()


def _parse_or_skip(raw: str) -> dict | None:
    """队列元素必须是合法信封JSON，否则如实报告并跳过该条"""
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"  该消息不是合法JSON，跳过: {e}\n  原文前200字符: {raw[:200]}\n")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="只读探查Redis里Celery的底层数据格式")
    parser.add_argument("--limit", type=int, default=3, help="队列消息最多解剖几条（默认3）")
    parser.add_argument("--results", action="store_true", help="附带查看结果后端的任务结果格式")
    args = parser.parse_args()

    r = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    try:
        r.ping()
    except redis.exceptions.ConnectionError as e:
        print(f"Redis连不上（先启动Redis再看）: {e}")
        return 1

    show_key_overview(r)
    show_queue_messages(r, args.limit)
    show_unacked(r)
    if args.results:
        show_results(args.limit)
    print("（探查结束。本脚本只读，未改动队列任何数据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
