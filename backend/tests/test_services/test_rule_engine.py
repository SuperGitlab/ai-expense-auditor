"""
规则引擎纯函数测试（无需DB/LLM，始终执行）
"""
from app.agents.rule_agent import evaluate_rules

MEAL_RULE = {
    "code": "MEAL_500", "name": "餐饮限额", "rule_type": "amount_limit",
    "category_id": 7, "field_name": "amount", "operator": "gt",
    "threshold": "500", "severity": "warn", "risk_points": 15,
}
NO_INVOICE_RULE = {
    "code": "NO_INVOICE", "name": "必须有发票", "rule_type": "invoice_required",
    "category_id": None, "field_name": "invoice_no", "operator": "not_exists",
    "threshold": None, "severity": "block", "risk_points": 50,
}
DUP_RULE = {
    "code": "DUP", "name": "重复发票", "rule_type": "duplicate_invoice",
    "category_id": None, "field_name": "invoice_no", "operator": "exists",
    "threshold": None, "severity": "block", "risk_points": 50,
}
BIG_TOTAL_RULE = {
    "code": "BIG", "name": "大额报销", "rule_type": "amount_limit",
    "category_id": None, "field_name": "total_amount", "operator": "gte",
    "threshold": "10000", "severity": "review", "risk_points": 25,
}
OLD_DATE_RULE = {
    "code": "OLD", "name": "超期费用", "rule_type": "date_limit",
    "category_id": None, "field_name": "expense_date", "operator": "gt",
    "threshold": "90", "severity": "warn", "risk_points": 10,
}


def snapshot(total, items):
    return {
        "expense": {"id": 1, "title": "t", "total_amount": total, "expense_type": "meal"},
        "items": items,
        "applicant": {"id": 1},
    }


def item(amount=100, invoice="INV12345678", date="2026-08-25", category=7, desc="说明"):
    return {"id": 1, "category_id": category, "amount": amount, "invoice_no": invoice,
            "expense_date": date, "description": desc}


def test_normal_expense_no_violation():
    """正常单据：无违规、0分、不拦截"""
    r = evaluate_rules(snapshot(300, [item(amount=300)]),
                       [MEAL_RULE, NO_INVOICE_RULE, BIG_TOTAL_RULE], [])
    assert r["violations"] == []
    assert r["points"] == 0
    assert not r["hard_blocked"]
    assert not r["forced_review"]


def test_meal_over_limit_warn():
    """超餐标：WARN计15分不拦截"""
    r = evaluate_rules(snapshot(800, [item(amount=800)]), [MEAL_RULE], [])
    assert len(r["violations"]) == 1
    assert r["points"] == 15
    assert not r["hard_blocked"]


def test_missing_invoice_blocks():
    """无发票：BLOCK硬拦截，分数不低于50"""
    r = evaluate_rules(snapshot(100, [item(invoice=None)]), [NO_INVOICE_RULE], [])
    assert r["hard_blocked"]
    assert r["points"] >= 50


def test_duplicate_invoice_blocks():
    """重复发票：BLOCK硬拦截"""
    dups = [{"invoice_no": "INV12345678", "expense_id": 9, "description": "旧单"}]
    r = evaluate_rules(snapshot(100, [item()]), [DUP_RULE], dups)
    assert r["hard_blocked"]
    assert len(r["violations"]) == 1
    assert "INV12345678" in r["violations"][0]["detail"]


def test_big_total_forces_review():
    """总额大额：REVIEW强制转人工但不拦截"""
    r = evaluate_rules(snapshot(15000, [item(amount=15000, category=None)]), [BIG_TOTAL_RULE], [])
    assert r["forced_review"]
    assert not r["hard_blocked"]


def test_old_expense_warns():
    """超期费用（超过90天）：WARN计分"""
    r = evaluate_rules(snapshot(100, [item(date="2026-01-01")]), [OLD_DATE_RULE], [])
    assert len(r["violations"]) == 1
    assert r["points"] == 10


def test_category_scoping():
    """类别限定规则只作用于对应类别明细"""
    # 餐饮规则（category_id=7），明细是办公类（category_id=5）→ 不命中
    r = evaluate_rules(snapshot(800, [item(amount=800, category=5)]), [MEAL_RULE], [])
    assert r["violations"] == []
