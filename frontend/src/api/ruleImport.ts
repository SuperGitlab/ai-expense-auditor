// 规则导入 API：JSON直导 / 制度文档抽取草稿 / 确认入库
import request from '@/utils/request'
import type { Rule, RuleOperator, RuleSeverity, RuleType } from '@/types'

// 与后端 schemas/rule_import.py 一一对应
export interface RuleImportItem {
  name: string
  code: string
  rule_type: RuleType
  category_code?: string | null
  category_id?: number | null
  field_name: string
  operator: RuleOperator
  threshold?: string | null
  severity: RuleSeverity
  risk_points: number
  description?: string | null
  is_active?: boolean
}

// 400逐行错误明细（与detail平级，拦截器弹toast、这里渲染表格）
export interface RowError {
  index: number
  code?: string | null
  errors: string[]
}

export interface ImportResult {
  imported: number
  rules: Rule[]
  vector_written: number
  vector_available: boolean
  cleared_policies: boolean
}

export function importRulesJson(rules: unknown[]): Promise<ImportResult> {
  return request.post('/rules/import/json', { rules })
}

export interface SectionOut {
  title: string
  content: string
}

export interface DraftRule extends RuleImportItem {
  quote: string
  issues: string[]
}

export interface ExtractionDraft {
  filename: string
  source: string
  sections: SectionOut[]
  rules: DraftRule[]
  stats: Record<string, number | string>
}

export function extractDocumentRules(file: File): Promise<ExtractionDraft> {
  const form = new FormData()
  form.append('file', file)
  return request.post('/rules/import/document/extract', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export interface DocumentConfirmPayload {
  source: string
  mode: 'append' | 'replace'
  rules: RuleImportItem[]
  sections: SectionOut[]
}

export function confirmDocumentImport(payload: DocumentConfirmPayload): Promise<ImportResult> {
  return request.post('/rules/import/document/confirm', payload)
}
