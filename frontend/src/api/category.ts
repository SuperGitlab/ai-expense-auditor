// 费用类别 API
import request from '@/utils/request'
import type { Category } from '@/types'

export function listCategories(): Promise<Category[]> {
  return request.get('/categories')
}
