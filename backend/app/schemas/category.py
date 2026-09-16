"""
费用类别数据模式
下拉读取与管理页增删改共用
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    """类别基础模式"""
    name: str = Field(..., min_length=1, max_length=100, description="类别名称")
    code: str = Field(..., min_length=1, max_length=50, description="类别代码（创建后不可改）")
    max_amount: Optional[float] = Field(None, ge=0, description="单次最高金额")
    description: Optional[str] = Field(None, max_length=200, description="类别描述")


class CategoryCreate(CategoryBase):
    """创建类别模式"""
    pass


class CategoryUpdate(BaseModel):
    """更新类别模式（不含code：创建后不可改，payload中的code会被忽略）"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    max_amount: Optional[float] = Field(None, ge=0)
    description: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None


class CategoryResponse(CategoryBase):
    """类别响应模式"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool = True


class CategoryDeleteResult(BaseModel):
    """删除结果（deleted=False 表示因历史报销明细引用转为停用、未物理删除）"""
    deleted: bool
    hidden_rules: int = Field(..., description="绑定该类别被停用并解绑的规则数")
    has_history: bool = Field(..., description="是否存在历史报销明细引用")
