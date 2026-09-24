"""
规则校验Agent
核心为确定性规则引擎（纯代码、可单测、不依赖LLM），
LLM仅负责把命中规则翻译成自然语言摘要。
"""
import json  # 把报销单/命中结果序列化成JSON文本，拼进LLM提示词
import logging  # 规则引擎日志（脏配置跳过等分支埋点）
from datetime import date  # 解析ISO格式费用日期，并用date.today()计算"距今N天"
from decimal import Decimal  # 金额比较用Decimal，避免float精度误差（财务场景必需）
from typing import Any, Dict  # 类型标注

from app.agents.base_agent import AgentResult, BaseAgent  # 基类：LLM客户端 + 统一的AgentResult返回结构
from app.models.rule import RuleOperator  # 规则操作符枚举（gt/lt/gte/lte/eq/in/exists/not_exists）

logger = logging.getLogger(__name__)


def _field_value(item: dict, field_name: str) -> Any:
    """从报销明细中取字段值（金额/日期/发票号/说明）"""
    # 字段名 -> 取值lambda的映射表；total_amount是整单级字段，
    # build_snapshot时已把它冗余挂到每条明细的_total_amount上，按明细字段统一取
    mapping = {
        "amount": lambda it: it.get("amount"),
        "expense_date": lambda it: it.get("expense_date"),
        "invoice_no": lambda it: it.get("invoice_no"),
        "description": lambda it: it.get("description"),
        "total_amount": lambda it: it.get("_total_amount"),
    }
    getter = mapping.get(field_name)  # 查表取出该字段对应的取值函数
    return getter(item) if getter else None  # 字段不在映射表（规则配了不支持的field）则返回None


def _days_ago(date_str: str) -> int:
    """日期字符串距今天数"""
    d = date.fromisoformat(date_str)  # "2026-08-01" -> date对象（格式非法会抛ValueError）
    return (date.today() - d).days  # 今天减去该日期 = 已过去的天数（未来日期为负数）


def _match(value: Any, operator: str, threshold: str | None) -> bool:
    """按操作符比较（threshold统一字符串存储，此处转型）"""
    try:
        # 数值类操作符：gt/lt/gte/lte/eq
        if operator in (RuleOperator.GT.value, RuleOperator.LT.value,
                        RuleOperator.GTE.value, RuleOperator.LTE.value, RuleOperator.EQ.value):
            # 金额类比较：两边都先str()再转Decimal（兼容value是int/float/str的情况）
            v, t = Decimal(str(value)), Decimal(str(threshold))
            # 一次性算出全部5种比较结果，再按operator取对应那个（写法紧凑，等价于if-elif链）
            return {
                "gt": v > t, "lt": v < t, "gte": v >= t, "lte": v <= t, "eq": v == t,
            }[operator]
        if operator == RuleOperator.IN.value:
            # in：threshold是逗号分隔的白名单，如"100,200,300"；去空格后做字符串精确匹配
            return str(value) in [s.strip() for s in (threshold or "").split(",")]
        if operator == RuleOperator.EXISTS.value:
            return bool(value)  # exists：字段有值（非None/非空串/非0）即命中
        if operator == RuleOperator.NOT_EXISTS.value:
            return not bool(value)  # not_exists：字段为空即命中
    except Exception:
        # 任何异常（threshold非数字、日期格式错等）一律视为不命中，
    # 保证单条脏规则不会让整个引擎崩掉
        return False
    return False  # 操作符不在枚举范围内：不命中


def evaluate_rules(snapshot: dict, rules: list[dict], duplicates: list[dict]) -> dict:
    """
    确定性规则引擎（纯函数，可单测）

    Args:
        snapshot: build_snapshot 的报销单快照
        rules: 规则列表（dict形式，含 rule_type/field_name/operator/threshold/severity/risk_points）
        duplicates: 已查出的重复发票 [{invoice_no, expense_id, description}]

    Returns:
        {violations, hard_blocked, forced_review, points, details}
    """
    expense = snapshot["expense"]  # 报销单主表信息（总额等整单级字段）
    items = snapshot["items"]  # 报销明细列表（逐条校验的对象）
    dup_invoices = {d["invoice_no"] for d in duplicates}  # 重复发票号集合（DUP_INVOICE分支用，O(1)查重）

    violations = []  # 所有命中记录的列表
    points = 0  # 累计风险分
    hard_blocked = False  # 是否命中"驳回"级规则（block）
    forced_review = False  # 是否命中"强制人工复审"级规则（review）

    def record(rule: dict, detail: str, item_id: int | None = None):
        """记一条命中：累计风险分、标记严重级别、写入violations列表"""
        # 闭包内要修改外层局部变量，需nonlocal声明
        nonlocal points, hard_blocked, forced_review
        severity = rule.get("severity", "warn")  # 规则严重级别，缺省warn（仅扣分）
        pts = int(rule.get("risk_points", 10))  # 该规则的风险分，缺省10分
        if severity == "block":
            # block级：直接触发硬驳回，且保底50分（确保分数足以反映严重性）
            hard_blocked = True
            pts = max(pts, 50)
        elif severity == "review":
            # review级：不驳回，但必须转人工复审
            forced_review = True
        points += pts  # 累加到总风险分
        violations.append({  # 落一条命中记录（供前端展示 + 拼给LLM做摘要）
            "rule_code": rule.get("code"),  # 规则编码，如 DUP_INVOICE
            "rule_name": rule.get("name"),  # 规则名称
            "severity": severity,  # 本条严重级别
            "risk_points": pts,  # 本条扣的分（block级已抬到>=50）
            "detail": detail,  # 人可读的命中描述
            "item_id": item_id,  # 关联的明细id（整单级规则为None）
        })

    for rule in rules:  # 逐条规则执行
        code = rule.get("code", "")  # 规则编码
        op = rule.get("operator", "")  # 比较操作符
        threshold = rule.get("threshold")  # 阈值（统一字符串存储）
        # 场景筛选：规则绑定了费用类别（category_id）时只校验该类别的明细；
        # 未绑定（None）则对全部明细生效
        target_items = [
            it for it in items
            if rule.get("category_id") is None or it.get("category_id") == rule.get("category_id")
        ]

        if code == "DUP_INVOICE" or rule.get("rule_type") == "duplicate_invoice":
            # 重复发票：直接使用预查结果
            # （重复检测需要查库比对历史报销单，不适合纯函数引擎，由上游先查好传入）
            if dup_invoices:  # 有重复发票才记命中（否则该规则静默通过）
                for d in duplicates:  # 每张重复发票单独记一条，指明被哪个报销单占用
                    record(rule, f"发票号 {d['invoice_no']} 已被报销单 #{d['expense_id']} 使用")
            continue  # 该规则处理完毕，进入下一条

        if rule.get("rule_type") == "date_limit":
            # 日期限制：threshold为天数，费用日期距今超过N天命中
            try:
                days = int(float(threshold))  # 阈值转天数（float中转是为了兼容"30.0"这类配置）
            except (TypeError, ValueError) as e:
                logger.debug("date_limit阈值非法，跳过该规则: code=%s, threshold=%r, err=%s",
                             code, threshold, e)
                continue  # 阈值没配/配错：跳过该规则，不让脏配置炸掉引擎
            for it in target_items:  # 逐条明细检查费用日期
                d = it.get("expense_date")
                if d and _days_ago(d) > days:  # 日期存在且距今超过N天 -> 命中
                    record(rule, f"费用日期 {d} 距今已超过{days}天", it.get("id"))
            continue

        # 通用字段比较（amount/invoice_no/description/total_amount）
        field = rule.get("field_name", "")
        if field == "total_amount":
            # 作用于整单：只比较报销总额一次，不逐明细
            v = expense.get("total_amount")
            if v is not None and _match(v, op, threshold):  # 总额存在且满足比较条件 -> 命中
                record(rule, f"报销总额 {v} 元命中规则（阈值 {threshold}）")
            continue

        # 其余字段：逐条明细比较
        for it in target_items:
            v = _field_value(it, field)  # 按字段名取该明细的值
            # invoice_no 的 exists/not_exists 直接判空
            # （发票号存在性有专用文案，不走通用_match，命中描述更友好）
            if field == "invoice_no":
                has = bool(it.get("invoice_no"))  # 该明细是否填了发票号
                if op == "not_exists" and not has:  # 要求"必须有"但没填 -> 命中
                    record(rule, f"明细#{it.get('id')} 缺少发票号", it.get("id"))
                elif op == "exists" and has:  # 要求"必须没有"但填了 -> 命中
                    record(rule, f"明细#{it.get('id')} 已提供发票号", it.get("id"))
                continue  # invoice_no分支结束，处理下一条明细
            if field == "description":
                # 费用说明同理：只处理"缺失"告警（exists对说明无业务意义，不记录）
                has = bool(it.get("description"))
                if op == "not_exists" and not has:
                    record(rule, f"明细#{it.get('id')} 缺少费用说明", it.get("id"))
                continue
            # 通用数值/枚举比较（amount等）：值存在且满足操作符条件 -> 命中
            if v is not None and _match(v, op, threshold):
                record(rule, f"明细#{it.get('id')} {field}={v} 命中（阈值 {threshold}）", it.get("id"))

    # 汇总返回：points封顶100（风险分是百分制）
    return {
        "violations": violations,  # 全部命中记录
        "hard_blocked": hard_blocked,  # True = 流程应直接驳回
        "forced_review": forced_review,  # True = 必须转人工复审
        "points": min(points, 100),  # 风险分（0-100）
        "duplicates": duplicates,  # 透传重复发票明细，供下游使用
    }


class RuleAgent(BaseAgent):
    """规则校验Agent：确定性引擎判定 + LLM生成自然语言摘要"""

    def __init__(self):
        super().__init__(name="规则校验Agent")  # 初始化基类：创建LLM客户端、对话记忆等

    def get_system_prompt(self) -> str:
        # 规则摘要的角色提示词：只做忠实翻译，不编造规则之外的信息
        # （判定结果来自确定性引擎，LLM胡说会误导审核人，故严格限定）
        return (
            "你是财务规则审核助手。给你一份报销单的规则命中结果（机器判定），"
            "请用简洁专业的中文总结违规情况，说明每条命中规则对报销合规性的影响。"
            "如果没有命中任何规则，说明该单据通过全部硬性规则校验。不要添加规则之外的信息。"
        )

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        input_data: {"expense": snapshot, "rules_data": {"rules": [...], "duplicates": [...]}}
        """
        snapshot = input_data["expense"]  # 报销单快照（expense + items）
        rules_data = input_data.get("rules_data", {})  # 规则与重复发票预查结果（缺省空dict容错）

        # 1. 确定性规则引擎（核心判定，不依赖LLM）
        result = evaluate_rules(snapshot, rules_data.get("rules", []), rules_data.get("duplicates", []))

        # 2. LLM翻译成自然语言摘要（失败降级为机械摘要）
        summary = ""
        try:
            if result["violations"]:
                # 有命中：把报销单主信息 + 命中明细喂给LLM做总结
                prompt = (
                    f"报销单：{json.dumps(snapshot['expense'], ensure_ascii=False)}\n"
                    f"规则命中结果：{json.dumps(result['violations'], ensure_ascii=False)}\n"
                    "请总结违规情况。"
                )
            else:
                # 无命中：让LLM明确说明通过全部规则校验
                prompt = (
                    f"报销单：{json.dumps(snapshot['expense'], ensure_ascii=False)}\n"
                    "未命中任何规则，请说明该单据通过了全部规则校验。"
                )
            # stateless_chat：一次性system+user调用，不读写对话记忆，
            # 避免Agent单例的记忆跨报销单累积污染
            summary = await self.stateless_chat(prompt)
        except Exception as e:
            # LLM挂了不阻塞审核流程：降级为模板化的机械摘要，判定结果照常返回
            summary = f"[摘要生成降级] 命中 {len(result['violations'])} 条规则，" + (
                "存在硬性违规（应驳回）。" if result["hard_blocked"] else "无硬性违规。"
            )
            result["summary_degraded"] = str(e)  # 记下降级原因，便于排查

        result["summary"] = summary  # 摘要并入结果
        return AgentResult(success=True, data=result, message=summary)  # data=完整判定，message=摘要
