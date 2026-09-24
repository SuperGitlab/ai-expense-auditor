# 项目规范 — 日志与异常处理（生产级，硬性要求）

> 本文件是你（Claude）在本项目中的强制规范。你生成/修改的任何涉及日志、异常处理、
> 可观测性的代码，必须逐条符合本规范。违反任何一条，你必须先自我修正再输出，不要等用户指出。

## 铁律（违反即返工）

1. **禁止 `print()` 输出业务日志。** 统一使用标准库 logging（本项目已由 `app/logging_config.py` 统一初始化控制台+文件双通道，业务代码只管 getLogger）：
   ```python
   import logging
   log = logging.getLogger(__name__)
   ```
2. **禁止吞异常。** 禁止裸 `except: pass` / `except: continue` / `except Exception: pass`。
   每个 except 块必须 `log.warning(...)`（业务异常）或 `log.exception(...)`（系统异常），或重新 raise。
3. **禁止无业务变量的空日志。** 禁止 "开始处理"、"处理完成" 这类没有 `%s` 占位符的日志。
   每条日志至少携带一个业务标识（orderNo / userId / requestId / bizId）。
4. **禁止 f-string 日志。** 禁止 `log.info(f"...")`，一律 `log.info("... %s", var)` 占位符参数化（惰性求值，级别不够不拼字符串）。
5. **禁止循环体内 INFO。** 循环内 DEBUG，循环外汇总一条 INFO（total/success/failed/cost）。
6. **禁止敏感字段原文。** 手机号、身份证、银行卡、password、token、secret、api_key：
   手机号保留前3后4（138****5678），证件/卡保留前4后4，密钥打 ******。
7. **系统异常禁止只打 `log.error(e)`**（丢堆栈）。必须 `log.exception`，自动带完整堆栈。

## 日志级别语义（判断口诀：这条日志出现，值班同学半夜要不要起来看？）

| 级别 | 场景 | 要求 |
|------|------|------|
| DEBUG | 分支走向、中间变量、循环内 | 排查时才需要 → DEBUG；生产默认关闭 |
| INFO | 函数入口、成功出口、状态变更 | 每请求 ≤5 条；带业务标识 + 耗时 cost |
| WARNING | 可预期业务异常：参数错误、记录不存在、外部返回失败、降级 | 不告警，但要可统计关注 |
| ERROR | 系统异常：DB/网络/第三方故障 | `log.exception` 带堆栈，必接告警 |
| CRITICAL | 服务无法继续：连接池耗尽、磁盘满 | 电话告警 |

## 函数埋点标准（每个对外接口/核心函数/定时任务必须包含四类埋点）

① 入口 INFO（关键入参 + 业务标识）→ ② 分支 DEBUG（每个关键 if/else + 决策变量值）
→ ③ 出口 INFO（结果标识 + 总耗时，perf_counter，保留1位小数 ms）→ ④ 异常埋点（见下）

```python
log = logging.getLogger(__name__)
start = time.perf_counter()
log.info("订单创建开始，orderNo=%s, userId=%s", order_no, user_id)
try:
    log.debug("库存校验通过，skuId=%s, stock=%s", sku_id, stock)
    pay_start = time.perf_counter()
    result = payment_client.pay(order_no, amount)
    log.info("支付调用完成，orderNo=%s, success=%s, cost=%.1fms",
             order_no, result.success, (time.perf_counter() - pay_start) * 1000)
    if not result.success:
        log.warning("支付失败（外部拒绝），orderNo=%s, code=%s, msg=%s",
                    order_no, result.code, result.msg)
        raise BizException(result.msg)
    cost = (time.perf_counter() - start) * 1000
    log.info("订单创建成功，orderNo=%s, userId=%s, cost=%.1fms",
             order_no, user_id, cost)
    return order
except BizException as e:
    log.warning("订单创建业务异常，userId=%s, reason=%s", user_id, e)
    raise
except Exception:
    log.exception("订单创建系统异常，userId=%s", user_id)
    raise
```

## 异常三分法（写每个 except 前先判断类型）

- **业务异常**（预期内、用户可感知：余额不足、参数错误）→ `log.warning` + 原样 raise，不告警
- **系统异常**（预期外、需人工介入：DB挂、超时）→ `log.exception` + raise，接告警
- **不可恢复**（进程无法继续）→ `log.critical`
- 包装异常必须 `raise NewError(...) from e` 保留因果链；禁止丢失原始堆栈

## 外部调用规范（DB / HTTP / Redis / MQ）

- 调用后 INFO：业务标识 + 结果状态 + 耗时 cost
- 调用失败 WARNING：业务标识 + 耗时 + 错误码/原因
- 慢调用告警（即使成功也打 WARNING）：DB 超 500ms、HTTP 超 2000ms

## 输出前自查（每次输出代码后，必须在回复末尾附上）

```
日志自查：
□ logging.getLogger + %s 占位符，无 print、无 f-string
□ 入口/分支/出口/异常 四类埋点齐全
□ 每条 INFO 至少一个业务标识变量
□ 异常三分法正确，无吞异常，系统异常 log.exception
□ 无敏感字段原文，已脱敏
□ 外部调用带耗时，超阈值有慢调用告警
```

任一项不满足 → 先修正代码再输出，并在自查声明中标注已修正项。

## 排查协作规则（用户报 bug 时）

当用户描述线上 bug 时，不要直接猜原因给修复方案。按此流程：
1. 先审查相关代码的日志埋点缺陷（哪些分支没日志、异常是否被吞）
2. 给出**最小补日志方案**（具体到文件/行/加什么日志），让用户补日志复现
3. 用户带回新日志后，基于日志证据定位根因，再给修复方案
4. 修复时补充该分支缺失的日志，防止下次再盲查
