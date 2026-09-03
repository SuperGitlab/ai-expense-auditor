// 规则管理 API
import request from '@/utils/request'
import type { Rule } from '@/types'

export function listRules(activeOnly = false): Promise<Rule[]> {
  return request.get('/rules', { params: activeOnly ? { active_only: true } : {} })
}

export function createRule(data: Partial<Rule>): Promise<Rule> {
  return request.post('/rules', data)
}

export function updateRule(id: number, data: Partial<Rule>): Promise<Rule> {
  return request.put(`/rules/${id}`, data)
}

export function deleteRule(id: number): Promise<void> {
  return request.delete(`/rules/${id}`)
}
