// 报销单相关 API
import request from '@/utils/request'
import type {
  AIReviewResult,
  Expense,
  ExpenseStatus,
  ExpenseType,
  PageResult,
} from '@/types'

export interface ExpenseQuery {
  page?: number
  page_size?: number
  status?: ExpenseStatus | null
  expense_type?: ExpenseType | null
}

export function listExpenses(params: ExpenseQuery): Promise<PageResult<Expense>> {
  return request.get('/expenses', { params })
}

// 全部报销单（监管视角：manager看本部门，finance/admin看全部）
export function listAllExpenses(params: ExpenseQuery): Promise<PageResult<Expense>> {
  return request.get('/expenses/all', { params })
}

export function getExpense(id: number): Promise<Expense> {
  return request.get(`/expenses/${id}`)
}

export function createExpense(data: Partial<Expense>): Promise<Expense> {
  return request.post('/expenses', data)
}

export function updateExpense(id: number, data: Partial<Expense>): Promise<Expense> {
  return request.put(`/expenses/${id}`, data)
}

export function deleteExpense(id: number): Promise<void> {
  return request.delete(`/expenses/${id}`)
}

export function submitExpense(id: number): Promise<Expense> {
  // 提交会自动触发AI审核工作流（低风险秒级自动通过）
  return request.post(`/expenses/${id}/submit`)
}

export function cancelExpense(id: number): Promise<Expense> {
  return request.post(`/expenses/${id}/cancel`)
}

// 财务打款登记（approved → paid；真实转账在系统外完成，这里只登记状态）
export function payExpense(id: number): Promise<Expense> {
  return request.post(`/expenses/${id}/pay`)
}

// 手动触发AI审核（本人/admin/finance；单据须为 submitted/pending）
export function triggerAIReview(expenseId: number): Promise<AIReviewResult> {
  return request.post('/agent/review', { expense_id: expenseId })
}
