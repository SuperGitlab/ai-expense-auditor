// AI审核工作流相关 API
import request from '@/utils/request'
import type { ExpenseStatus } from '@/types'

// 节点执行状态：pending=待执行（前端补齐）/ running / succeeded / failed / overridden（人审结果优先）
export type NodeRunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'overridden'

export interface AgentNodeExecution {
  node: string
  label: string
  status: NodeRunStatus
  started_at: string | null
  finished_at: string | null
  detail: string | null
  error: string | null
}

export interface AgentExecutions {
  nodes: AgentNodeExecution[]
  expense_status: ExpenseStatus
  can_retry: boolean
}

// 节点执行轨迹（工作流画布数据源，3s轮询）
// skipErrorMessage：轮询闪断不弹统一错误窗（连续失败由画布自行停轮询提示）
export function getExecutions(expenseId: number): Promise<AgentExecutions> {
  return request.get(`/agent/executions/${expenseId}`, { skipErrorMessage: true })
}

// 断点恢复重跑：已成功节点直接复用，仅重跑未完成节点
export function retryExecution(expenseId: number): Promise<{ expense_id: number; dispatched: boolean; resume: boolean }> {
  return request.post(`/agent/executions/${expenseId}/retry`)
}
