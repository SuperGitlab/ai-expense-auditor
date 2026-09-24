// 全局字典：状态/类型/风险等级的中文标签与标签颜色
import type { RuleOperator, RuleSeverity, RuleType } from '@/types'

// 注意：键放宽为string——模板里经常用后端返回的string状态值索引（如 by_status 遍历），
// 用Record<ExpenseStatus,...>会触发TS7053隐式any报错
export const STATUS_MAP: Record<string, { label: string; type: 'info' | 'primary' | 'warning' | 'success' | 'danger' }> = {
  draft: { label: '草稿', type: 'info' },
  submitted: { label: '已提交', type: 'primary' },
  pending: { label: '待审批', type: 'warning' },
  manager_approved: { label: '待财务终审', type: 'primary' },
  approved: { label: '已通过', type: 'success' },
  rejected: { label: '已驳回', type: 'danger' },
  paid: { label: '已支付', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
}

// 键放宽为string，原因同STATUS_MAP（模板里any类型索引会触发TS7053）
export const EXPENSE_TYPE_MAP: Record<string, string> = {
  travel: '差旅费',
  meal: '餐饮费',
  transportation: '交通费',
  accommodation: '住宿费',
  office: '办公费',
  other: '其他',
}

export const RISK_MAP: Record<string, { label: string; type: 'success' | 'warning' | 'danger'; color: string }> = {
  low: { label: '低风险', type: 'success', color: '#67c23a' },
  medium: { label: '中风险', type: 'warning', color: '#e6a23c' },
  middle: { label: '中风险', type: 'warning', color: '#e6a23c' }, // 兼容旧值
  high: { label: '高风险', type: 'danger', color: '#f56c6c' },
}

export const RULE_TYPE_MAP: Record<RuleType, string> = {
  amount_limit: '金额限制',
  invoice_required: '发票要求',
  date_limit: '日期限制',
  duplicate_invoice: '重复发票',
  category_restrict: '类别限制',
  custom: '自定义',
}

export const SEVERITY_MAP: Record<RuleSeverity, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  block: { label: '驳回', type: 'danger' },
  review: { label: '转人工', type: 'warning' },
  warn: { label: '计分', type: 'info' },
}

export const OPERATOR_MAP: Record<RuleOperator, string> = {
  gt: '大于',
  lt: '小于',
  gte: '大于等于',
  lte: '小于等于',
  eq: '等于',
  in: '在集合内',
  exists: '存在/非空',
  not_exists: '缺失/为空',
}

// 规则作用字段（与后端规则引擎 _field_value 映射约定；total_amount=整单总额）
export const RULE_FIELD_OPTIONS: { value: string; label: string }[] = [
  { value: 'amount', label: '金额(amount)' },
  { value: 'total_amount', label: '单据总额(total_amount)' },
  { value: 'expense_date', label: '费用日期(expense_date)' },
  { value: 'invoice_no', label: '发票号(invoice_no)' },
  { value: 'description', label: '费用说明(description)' },
]

export const AI_DECISION_MAP: Record<string, string> = {
  auto_approve: '自动通过',
  manual_review: '转人工审批',
  auto_reject: '自动驳回',
}

// 金额千分位格式化
export function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined) return '0.00'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
