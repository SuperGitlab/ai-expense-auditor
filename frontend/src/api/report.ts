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

// 导出报表Excel（blob下载；拦截器已返回response.data，此处即Blob）
export async function exportReport(months = 6): Promise<void> {
  const blob = (await request.get('/reports/export', {
    params: { months },
    responseType: 'blob',
  })) as Blob
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `报表_${new Date().toISOString().slice(0, 10)}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}
