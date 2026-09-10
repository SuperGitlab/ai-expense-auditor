// 站内通知 API
import request from '@/utils/request'
import type { NotificationItem, NotificationPage, NotificationType } from '@/types'

export function getNotifications(page = 1, pageSize = 10): Promise<NotificationPage> {
  return request.get('/notifications', { params: { page, page_size: pageSize } })
}

export function getUnreadCount(): Promise<{ count: number }> {
  return request.get('/notifications/unread-count')
}

export function markRead(id: number): Promise<NotificationItem> {
  return request.post(`/notifications/${id}/read`)
}

export function markAllRead(): Promise<{ updated: boolean }> {
  return request.post('/notifications/read-all')
}

// 通知类型 → 标签文案/颜色（铃铛下拉用）
export const TYPE_LABELS: Record<string, string> = {
  ai_review: 'AI审核',
  approval: '审批',
  payment: '打款',
  system: '系统',
}

export const TYPE_TAG_TYPES: Record<NotificationType, 'success' | 'warning' | 'info'> = {
  ai_review: 'warning',
  approval: 'success',
  payment: 'info',
  system: 'info',
}
