"""
规则接口
审核规则的管理（admin写、登录可读）
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DBSession, require_roles
from app.models import Rule, User, UserRole
from app.schemas.rule import RuleCreate, RuleResponse, RuleUpdate

router = APIRouter(prefix="/api/rules", tags=["规则管理"])

# 管理员依赖
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=list[RuleResponse])
def list_rules(
    db: DBSession,
    current_user: CurrentUser,
    active_only: bool = False,
):
    """规则列表（登录即可读，供前端展示规则说明）"""
    query = db.query(Rule)
    if active_only:
        query = query.filter(Rule.is_active == True)  # noqa: E712
    return query.order_by(Rule.id).all()


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(data: RuleCreate, db: DBSession, current_user: AdminUser):
    """创建规则（admin）"""
    if db.query(Rule).filter(Rule.code == data.code).first():
        raise HTTPException(status_code=409, detail=f"规则代码 {data.code} 已存在")
    rule = Rule(**data.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=RuleResponse)
def update_rule(rule_id: int, data: RuleUpdate, db: DBSession, current_user: AdminUser):
    """更新规则（admin）"""
    rule = db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: DBSession, current_user: AdminUser):
    """删除规则（admin，建议用停用代替删除）"""
    rule = db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    db.delete(rule)
    db.commit()
