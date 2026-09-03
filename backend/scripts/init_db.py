"""
数据库初始化脚本
建表 + 种子数据（用户/费用类别/审核规则），幂等可重复执行

用法（在 backend/ 目录下）:
    uv run python scripts/init_db.py
"""
import sys
from pathlib import Path

# 将 backend/ 加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.models import (Base, Category, Rule, User,  # noqa: E402
                        RuleOperator, RuleSeverity, RuleType, UserRole)
from app.services.auth_service import hash_password  # noqa: E402


def seed_users(db: Session) -> None:
    """种子用户：4个演示账号（先查后插，幂等）"""
    demo_users = [
        ("admin", "admin123", "系统管理员", UserRole.ADMIN, "信息技术部", "系统管理员"),
        ("finance01", "finance123", "王财务", UserRole.FINANCE, "财务部", "财务专员"),
        ("manager01", "manager123", "李经理", UserRole.MANAGER, "市场部", "部门经理"),
        ("employee01", "employee123", "张员工", UserRole.EMPLOYEE, "市场部", "市场专员"),
    ]
    for username, password, full_name, role, department, position in demo_users:
        if db.query(User).filter(User.username == username).first():
            continue
        db.add(User(
            username=username,
            email=f"{username}@company.com",
            hashed_password=hash_password(password),
            full_name=full_name,
            department=department,
            position=position,
            role=role,
        ))
        print(f"  + 用户: {username} / {password} ({role.value})")
    db.commit()


def seed_categories(db: Session) -> None:
    """种子费用类别：6类含单次限额（先查后插，幂等）"""
    categories = [
        ("差旅费", "travel", 5000, "机票、火车票等差旅支出"),
        ("餐饮费", "meal", 500, "工作餐、招待餐费"),
        ("市内交通费", "transportation", 1000, "出租车、网约车等"),
        ("住宿费", "accommodation", 2000, "出差酒店住宿"),
        ("办公用品费", "office", 3000, "办公耗材、设备"),
        ("其他费用", "other", 1000, "未归类支出"),
    ]
    for name, code, max_amount, description in categories:
        if db.query(Category).filter(Category.code == code).first():
            continue
        db.add(Category(name=name, code=code, max_amount=max_amount, description=description))
        print(f"  + 类别: {name}（限额 {max_amount} 元）")
    db.commit()


def seed_rules(db: Session) -> None:
    """种子审核规则：8条示例（先查后插，幂等）"""
    db.commit()  # 确保类别已可查询
    meal = db.query(Category).filter(Category.code == "meal").first()

    rules = [
        # (code, name, type, category_id, field, operator, threshold, severity, points, desc)
        ("MEAL_500", "餐饮单笔限额500元", RuleType.AMOUNT_LIMIT,
         meal.id if meal else None, "amount", RuleOperator.GT, "500",
         RuleSeverity.WARN, 15, "餐饮费单笔超过500元，计入风险分"),
        ("NO_INVOICE", "报销必须提供发票号", RuleType.INVOICE_REQUIRED,
         None, "invoice_no", RuleOperator.NOT_EXISTS, None,
         RuleSeverity.BLOCK, 50, "缺少发票号的报销项目直接驳回"),
        ("DUP_INVOICE", "发票号不得重复报销", RuleType.DUPLICATE_INVOICE,
         None, "invoice_no", RuleOperator.EXISTS, None,
         RuleSeverity.BLOCK, 50, "同一发票号已被其他报销单使用"),
        ("OLD_EXPENSE", "费用发生不得超过90天", RuleType.DATE_LIMIT,
         None, "expense_date", RuleOperator.GT, "90",
         RuleSeverity.WARN, 10, "费用发生日期距今超过90天，计入风险分"),
        ("BIG_TOTAL", "单张报销总额上限10000元", RuleType.AMOUNT_LIMIT,
         None, "total_amount", RuleOperator.GTE, "10000",
         RuleSeverity.REVIEW, 25, "单张报销单总额达到10000元，转人工审批"),
        ("NIGHT_HOTEL", "住宿单笔上限2000元", RuleType.AMOUNT_LIMIT,
         None, "amount", RuleOperator.GT, "2000",
         RuleSeverity.WARN, 15, "住宿费单笔超过2000元，计入风险分"),
        ("MEAL_DESC_CHECK", "餐饮说明必填", RuleType.CATEGORY_RESTRICT,
         meal.id if meal else None, "description", RuleOperator.NOT_EXISTS, None,
         RuleSeverity.WARN, 5, "餐饮费用说明缺失时计入风险分"),
        ("TRANSPORT_1000", "交通单笔上限1000元", RuleType.AMOUNT_LIMIT,
         None, "amount", RuleOperator.GT, "1000",
         RuleSeverity.WARN, 15, "市内交通单笔超过1000元，计入风险分"),
    ]
    for code, name, rtype, cat_id, field, op, thr, sev, pts, desc in rules:
        if db.query(Rule).filter(Rule.code == code).first():
            continue
        db.add(Rule(
            code=code, name=name, rule_type=rtype, category_id=cat_id,
            field_name=field, operator=op, threshold=thr,
            severity=sev, risk_points=pts, description=desc,
        ))
        print(f"  + 规则: {code} [{sev.value}] {name}")
    db.commit()


def main() -> None:
    print("=" * 50)
    print("数据库初始化开始")
    print("=" * 50)

    # 1. 建表（幂等）
    Base.metadata.create_all(bind=engine)
    print("[1/3] 建表完成（已存在的表跳过）")

    # 2. 种子数据
    db = SessionLocal()
    try:
        print("[2/3] 写入种子数据:")
        seed_users(db)
        seed_categories(db)
        seed_rules(db)
    finally:
        db.close()

    print("[3/3] 初始化完成 ✓")
    print("\n演示账号:")
    print("  admin     / admin123     （管理员）")
    print("  finance01 / finance123   （财务）")
    print("  manager01 / manager123   （部门经理）")
    print("  employee01/ employee123  （普通员工）")


if __name__ == "__main__":
    main()
