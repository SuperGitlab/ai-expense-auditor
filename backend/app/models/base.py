"""
数据库基础模型
所有模型的基类
"""
from sqlalchemy import Column, DateTime, func
from sqlalchemy.orm import DeclarativeBase, declared_attr


class CustoBase:
    """
    自定义基类
    提供通用字段和方法
    """

    # 自动生成表名（类名小写 + s），子类显式定义 __tablename__ 时以子类为准
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower() + "s"

    # 通用时间字段
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# 以 CustoBase 为混入、DeclarativeBase 为底座，所有模型继承 Base
# 2.0 风格写法：与 declarative_base(cls=CustoBase) 行为一致，
# 但 metadata/registry 有静态类型声明，IDE 可跳转、可补全
class Base(CustoBase, DeclarativeBase):
    pass
