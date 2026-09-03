// 报表统计 API（finance/admin）
import request from '@/utils/request'
import type { CategoryStat, ReportSummary, TrendMonth } from '@/types'

export function getSummary(): Promise<ReportSummary> {
  return request.get('/reports/summary')
}

export function getTrends(months = 6): Promise<{ months: TrendMonth[] }> {
  return request.get('/reports/trends', { params: { months } })
}

export function getByCategory(): Promise<{ categories: CategoryStat[] }> {
  return request.get('/reports/by-category')
}
