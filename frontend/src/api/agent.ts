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

// 队列探查（仅 SUBMITTED 且未开跑时返回，其余为 null）：
// queued=排队中(ahead=前面还有几单，含已被领取的) / executing=已被worker领取未ack /
// missing=不在队列也未被领取（消息可能丢失） / unknown=探查失败
export interface QueueStatus {
  state: 'queued' | 'executing' | 'missing' | 'unknown'
  ahead?: number
}

export interface AgentExecutions {
  nodes: AgentNodeExecution[]
  expense_status: ExpenseStatus
  can_retry: boolean
  queue_status: QueueStatus | null
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
