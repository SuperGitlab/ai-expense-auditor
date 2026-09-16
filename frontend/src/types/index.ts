// 与后端 Pydantic schema 一一对应的 TS 类型定义

// ========== 用户 ==========
export type UserRole = 'admin' | 'finance' | 'manager' | 'employee'

export interface UserInfo {
  id: number
  username: string
  email: string
  full_name: string | null
  phone: string | null
  department: string | null
  position: string | null
  role: UserRole
  is_active: boolean
  is_superuser: boolean
  last_login_at: string | null
  created_at: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  user: UserInfo
}

// ========== 费用类别 ==========
export interface Category {
  id: number
  name: string
  code: string
  max_amount: number | null
  description: string | null
  is_active?: boolean // 仅管理页（include_inactive）返回
}

// ========== 报销单 ==========
export type ExpenseStatus =
  | 'draft'
  | 'submitted'
  | 'pending'
  | 'manager_approved'
  | 'approved'
  | 'rejected'
  | 'paid'
  | 'cancelled'

export type ExpenseType =
  | 'travel'
  | 'meal'
  | 'transportation'
  | 'accommodation'
  | 'office'
  | 'other'

export interface ExpenseItem {
  id?: number
  expense_id?: number
  category_id: number
  description: string
  amount: number
  expense_date: string // YYYY-MM-DD
  invoice_no: string | null
  invoice_url: string | null
  invoice_verified?: boolean
  created_at?: string
}

export interface Expense {
  id: number
  user_id: number
  // 申请人信息（"全部报销"监管视角列表返回；其他接口为null）
  applicant_name?: string | null
  applicant_department?: string | null
  expense_no: string
  title: string
  expense_type: ExpenseType
  description: string | null
  remark: string | null
  total_amount: number
  currency: string
  status: ExpenseStatus
  risk_level: string | null // low / medium / high
  risk_score: number | null
  ai_review_result: string | null
  rejection_reason: string | null // 驳回原因（rejected时有值）
  submitted_at: string | null
  approved_at: string | null
  paid_at: string | null
  created_at: string
  updated_at: string | null
  items: ExpenseItem[]
}

// 分页响应（后端 utils/helpers.paginate 的结构）
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ========== 审批 ==========
export interface ApprovalRecord {
  id: number
  expense_id: number
  approver_id: number | null
  approver_name: string
  action: 'submit' | 'ai_review' | 'approve' | 'reject'
  comment: string | null
  risk_level: string | null
  risk_score: number | null
  ai_decision: string | null
  step: 'manager' | 'finance' | null
  created_at: string
}

export interface PendingExpense {
  id: number
  status: ExpenseStatus
  expense_no: string
  title: string
  user_id: number
  applicant_name: string | null
  total_amount: number
  risk_level: string | null
  risk_score: number | null
  submitted_at: string | null
}

// ========== 规则 ==========
export type RuleType =
  | 'amount_limit'
  | 'invoice_required'
  | 'date_limit'
  | 'duplicate_invoice'
  | 'category_restrict'
  | 'custom'

export type RuleSeverity = 'block' | 'warn' | 'review'

export type RuleOperator =
  | 'gt'
  | 'lt'
  | 'gte'
  | 'lte'
  | 'eq'
  | 'in'
  | 'exists'
  | 'not_exists'

export interface Rule {
  id: number
  name: string
  code: string
  rule_type: RuleType
  category_id: number | null
  field_name: string
  operator: RuleOperator
  threshold: string | null
  severity: RuleSeverity
  risk_points: number
  description: string | null
  is_active: boolean
  created_at: string | null
  updated_at: string | null
}

// ========== 报表 ==========
export interface ReportSummary {
  total: number
  total_amount: number
  by_status: Record<string, number>
  avg_risk_score: number
  month_count: number
  generated_at: string
}

export interface TrendMonth {
  month: string // YYYY-MM
  count: number
  amount: number
}

export interface CategoryStat {
  name: string
  amount: number
  count: number
  ratio: number // 0-1
}

// ========== AI 审核 ==========
export interface AIReviewResult {
  expense_id: number
  risk_level: string
  risk_score: number
  decision: 'auto_approve' | 'manual_review' | 'auto_reject'
  review_result: string
  suggestions: string[]
  relevant_rules: string[]
  similar_cases: Record<string, unknown>[]
  rule_violations: Record<string, unknown>[]
  workflow_errors: string[]
  elapsed_seconds: number | null
}

// ========== 站内通知 ==========
export type NotificationType = 'ai_review' | 'approval' | 'payment' | 'system'

export interface NotificationItem {
  id: number
  user_id: number
  title: string
  content: string | null
  type: NotificationType
  is_read: boolean
  created_at: string
}

// 后端通知列表 = paginate结构 + unread_count
export interface NotificationPage extends PageResult<NotificationItem> {
  unread_count: number
}
