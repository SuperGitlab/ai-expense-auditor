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

// 草稿表格行（文档抽取/JSON解析两通道共用的可编辑行：勾选态由前端持有）
export interface DraftRow extends DraftRule {
  selected: boolean
}

export interface ExtractionDraft {
  filename: string
  source: string
  sections: SectionOut[]
  rules: DraftRule[]
  stats: Record<string, number | string>
}

// 抽取任务提交回执（解析在Celery后台跑，接口只做校验+落盘+派发，毫秒级返回）
export interface ExtractionSubmit {
  task_id: string
  filename: string
}

// 抽取任务状态（前端轮询；SUCCESS携带草稿、FAILURE携带错误）
export interface ExtractionStatus {
  state: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE'
  draft?: ExtractionDraft | null
  error?: string | null
}

export function extractDocumentRules(file: File): Promise<ExtractionSubmit> {
  const form = new FormData()
  form.append('file', file)
  // 只等"上传+派发"（≤10MB），不等LLM解析
  return request.post('/rules/import/document/extract', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60_000,
  })
}

export function getExtractionStatus(taskId: string): Promise<ExtractionStatus> {
  return request.get(`/rules/import/document/extract/${taskId}`)
}

// 确认要写MySQL+Milvus（逐章节embedding），慢请求：放宽到5.5分钟，
// 略大于后端LLM超时(300s)，让后端错误真实到达前端而非axios先超时
const DOC_IMPORT_TIMEOUT = 330_000

export interface DocumentConfirmPayload {
  source: string
  mode: 'append' | 'replace'
  rules: RuleImportItem[]
  sections: SectionOut[]
}

export function confirmDocumentImport(payload: DocumentConfirmPayload): Promise<ImportResult> {
  // 确认要写Milvus（逐章节embedding），同样放宽超时
  return request.post('/rules/import/document/confirm', payload, {
    timeout: DOC_IMPORT_TIMEOUT,
  })
}
