// 审批相关 API
import request from '@/utils/request'
import type { ApprovalRecord, PendingExpense } from '@/types'

export function listPending(): Promise<PendingExpense[]> {
  return request.get('/approvals/pending')
}

// AI执行中列表（SUBMITTED）：审批中心「AI 审核中」栏数据源
export function listRunning(): Promise<PendingExpense[]> {
  return request.get('/approvals/running')
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

// 人工接管（人审优先）：AI执行中/待初审/待终审的单据可随时直接裁决，
// AI之后算出的结论只留档不生效；驳回必须填写意见
export function takeoverDecision(
  expenseId: number,
  action: 'approve' | 'reject',
  comment?: string,
): Promise<PendingExpense> {
  return request.post('/approvals/takeover', { expense_id: expenseId, action, comment })
}
