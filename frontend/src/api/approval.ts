// 审批相关 API
import request from '@/utils/request'
import type { ApprovalRecord, PendingExpense } from '@/types'

export function listPending(): Promise<PendingExpense[]> {
  return request.get('/approvals/pending')
}

export function getApprovalHistory(expenseId: number): Promise<{
  items: ApprovalRecord[]
  total: number
}> {
  return request.get(`/approvals/${expenseId}/history`)
}

export function decideApproval(
  expenseId: number,
  action: 'approve' | 'reject',
  comment?: string,
): Promise<PendingExpense> {
  return request.post('/approvals/decide', { expense_id: expenseId, action, comment })
}
