// 费用类别 API
import request from '@/utils/request'
import type { Category } from '@/types'

export interface CategoryDeleteResult {
  deleted: boolean // false=因历史明细引用转为停用、未物理删除
  hidden_rules: number
  has_history: boolean
}

// 更新载荷（code 创建后不可改，不在此列）
export interface CategoryPayload {
  name?: string
  max_amount?: number | null
  description?: string | null
  is_active?: boolean
}

export function listCategories(includeInactive = false): Promise<Category[]> {
  return request.get('/categories', { params: includeInactive ? { include_inactive: true } : {} })
}

export function createCategory(data: CategoryPayload & { code: string }): Promise<Category> {
  return request.post('/categories', data)
}

export function updateCategory(id: number, data: CategoryPayload): Promise<Category> {
  return request.put(`/categories/${id}`, data)
}

export function deleteCategory(id: number): Promise<CategoryDeleteResult> {
  return request.delete(`/categories/${id}`)
}
