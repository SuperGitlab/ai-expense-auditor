"""
批量提交报销单（压测/演示脚本）：登录演示账号 → 连续建单+提交N张
每张提交都会向Celery派发一个AI审核任务——配合worker观察队列并发消费。

用法（backend/ 目录下）：
    uv run python scripts/bulk_submit.py                    # 默认10张，employee01
    uv run python scripts/bulk_submit.py --count 5 --base-url http://localhost:8000

前提：后端API(8000) + Redis + worker 都在跑，否则提交返回503（单据留草稿）。
注意：每张单都会真实调用GLM（Agent审核2-3分钟/张），10张≈10次LLM审核费用。
"""
import argparse
import sys
from datetime import date
from time import strftime

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="批量创建并提交报销单（触发N个AI审核任务）")
    parser.add_argument("--base-url", default="http://localhost:8000", help="后端地址")
    parser.add_argument("--count", type=int, default=10, help="提交张数（默认10）")
    parser.add_argument("--username", default="employee01", help="登录账号（演示账号）")
    parser.add_argument("--password", default="employee123", help="密码")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=30)

    # 登录拿token
    resp = client.post("/api/auth/login-json", json={
        "username": args.username, "password": args.password,
    })
    if resp.status_code != 200:
        print(f"登录失败 {resp.status_code}: {resp.text}")
        return 1
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    print(f"已登录 {args.username}，开始提交 {args.count} 张报销单\n")

    # 时间戳后缀：保证每张单发票号唯一（重复发票是BLOCK级规则，会被硬拦）
    stamp = strftime("%Y%m%d%H%M%S")
    ok, failed = 0, 0
    for i in range(1, args.count + 1):
        payload = {
            "title": f"批量压测单{i:02d}",
            "expense_type": "meal",
            "items": [
                {
                    "category_id": 2,
                    "description": f"批量测试工作餐#{i}",
                    "amount": "50.00",
                    "expense_date": date.today().isoformat(),
                    "invoice_no": f"INV-BULK-{stamp}-{i:02d}",
                }
            ],
        }
        create = client.post("/api/expenses", json=payload, headers=headers)
        if create.status_code != 201:
            print(f"#{i:02d} 创建失败 {create.status_code}: {create.text}")
            failed += 1
            continue
        body = create.json()
        expense_id, expense_no = body["id"], body["expense_no"]

        submit = client.post(f"/api/expenses/{expense_id}/submit", headers=headers)
        if submit.status_code == 200:
            ok += 1
            print(f"#{i:02d} {expense_no} (id={expense_id}) 提交成功，AI审核任务已入队")
        elif submit.status_code == 503:
            print(f"#{i:02d} {expense_no} 提交503：Redis或worker未启动（单据留草稿）")
            failed += 1
        else:
            print(f"#{i:02d} {expense_no} 提交失败 {submit.status_code}: {submit.text}")
            failed += 1

    print(f"\n完成：成功 {ok} 张 / 失败 {failed} 张")
    print("AI审核由worker异步执行：看worker终端日志，或前端画布轮询节点点亮；")
    print("卡住的可用画布「重新执行」按钮或重启worker自愈。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
