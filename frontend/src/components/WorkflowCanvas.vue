<script setup lang="ts">
// 工作流画布：5个Agent节点执行状态实时可视化（自绘div+CSS箭头，对齐README流程图）
// 单据解析 →（规则校验 ∥ RAG检索）→ 风险评估 → 终审裁决
// 3s轮询轨迹接口；审批人可随时人工接管（人审优先：AI结论以人工结果为准）
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getExecutions, retryExecution } from '@/api/agent'
import { takeoverDecision } from '@/api/approval'
import type { AgentNodeExecution, NodeRunStatus } from '@/api/agent'
import { useUserStore } from '@/stores/user'

const props = defineProps<{ expenseId: number }>()
const emit = defineEmits<{ (e: 'decided'): void }>()

const POLL_INTERVAL = 3000

// 画布固定结构：4列（第2列rule/rag并行堆叠）
const STAGE_COLUMNS: string[][] = [['document'], ['rule', 'rag'], ['risk'], ['decision']]

const nodes = ref<AgentNodeExecution[]>([])
const expenseStatus = ref<string | null>(null)
const canRetryFlag = ref(false)
const loadFailed = ref(false)
let timer: number | null = null
let failCount = 0

const userStore = useUserStore()

const byNode = (name: string): AgentNodeExecution | undefined =>
  nodes.value.find((n) => n.node === name)

// 接管按钮显隐按角色对齐后端矩阵（跨部门等细节由后端兜底）：
// manager: submitted/pending（限本部门）；finance/admin: 三状态皆可
// （finance 对 submitted/pending 为紧急快速通道，批准直达已通过）
const canTakeover = computed(() => {
  const s = expenseStatus.value
  if (!s) return false
  switch (userStore.role) {
    case 'manager':
      return ['submitted', 'pending'].includes(s)
    case 'finance':
    case 'admin':
      return ['submitted', 'pending', 'manager_approved'].includes(s)
    default:
      return false
  }
})

const hasRunning = computed(() => nodes.value.some((n) => n.status === 'running'))

// 重跑按钮：服务端算好的 can_retry（本人/finance/admin + SUBMITTED/PENDING）且当前无节点在跑
const canRetry = computed(() => canRetryFlag.value && !hasRunning.value)

// 状态 → 节点框样式类
const STATUS_ICON: Record<NodeRunStatus, string> = {
  pending: 'Clock',
  running: 'Loading',
  succeeded: 'CircleCheck',
  failed: 'CircleClose',
  overridden: 'UserFilled',
}

const STATUS_TAG: Record<NodeRunStatus, string> = {
  pending: '待执行',
  running: '执行中',
  succeeded: '完成',
  failed: '失败',
  overridden: '人审结果优先',
}

function formatTime(t: string | null | undefined): string {
  return t ? t.replace('T', ' ').slice(0, 19) : '-'
}

// tooltip：摘要/错误 + 起止时间
function nodeTip(n: AgentNodeExecution | undefined): string {
  if (!n || n.status === 'pending') return '等待上游节点完成'
  const lines = [`${STATUS_TAG[n.status]}`]
  if (n.error) lines.push(`错误：${n.error}`)
  else if (n.detail) lines.push(n.detail)
  lines.push(`开始 ${formatTime(n.started_at)} / 结束 ${formatTime(n.finished_at)}`)
  return lines.join('\n')
}

async function load() {
  try {
    const data = await getExecutions(props.expenseId)
    nodes.value = data.nodes
    expenseStatus.value = data.expense_status
    canRetryFlag.value = data.can_retry
    loadFailed.value = false
    failCount = 0
    maybeStopPolling()
  } catch {
    failCount += 1
    // 连续2次失败：停轮询显示错误态（单次闪断静默重试）
    if (failCount >= 2) {
      loadFailed.value = true
      stopPolling()
    }
  }
}

// 全部节点到达终态（succeeded/failed/overridden）→ 轨迹不再变化，停止轮询
function maybeStopPolling() {
  const allDone =
    nodes.value.length > 0 &&
    nodes.value.every((n) => ['succeeded', 'failed', 'overridden'].includes(n.status))
  if (allDone) stopPolling()
}

function startPolling() {
  stopPolling()
  failCount = 0
  loadFailed.value = false
  load()
  timer = window.setInterval(load, POLL_INTERVAL)
}

function stopPolling() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(startPolling)
onBeforeUnmount(stopPolling)
// 抽屉内切换单据：重置状态重新轮询
watch(
  () => props.expenseId,
  () => {
    nodes.value = []
    expenseStatus.value = null
    canRetryFlag.value = false
    startPolling()
  },
)

// ===== 断点恢复重跑 =====
const retrying = ref(false)

async function doRetry() {
  try {
    await ElMessageBox.confirm(
      '已完成节点将直接复用，仅重跑未完成节点（不重复调用AI）。确认重新执行？',
      '重新执行AI审核',
      { confirmButtonText: '确认重跑', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  retrying.value = true
  try {
    await retryExecution(props.expenseId)
    ElMessage.success('已派发重跑，节点将从未完成处继续')
    startPolling() // 轨迹恢复变化（轮询可能已停）
  } catch {
    // 拦截器已提示（如执行中409、终态400）
  } finally {
    retrying.value = false
  }
}

// ===== 人工接管（人审优先） =====
const taking = ref(false)

async function doTakeover(action: 'approve' | 'reject') {
  let comment: string | undefined
  if (action === 'reject') {
    try {
      const { value } = await ElMessageBox.prompt(
        '人工接管驳回：请填写驳回原因（必填）',
        '驳回报销单',
        {
          confirmButtonText: '确认驳回',
          cancelButtonText: '取消',
          inputPlaceholder: '驳回原因',
          inputValidator: (v: string) => (v && v.trim() ? true : '驳回必须填写意见'),
        },
      )
      comment = value.trim()
    } catch {
      return // 用户取消
    }
  }
  taking.value = true
  try {
    await takeoverDecision(props.expenseId, action, comment)
    ElMessage.success(action === 'approve' ? '已人工接管：通过' : '已人工接管：驳回')
    emit('decided')
    load() // 立即刷新（AI可能仍在跑，轨迹后续会标记“人审结果优先”）
  } catch {
    // 拦截器已提示（如跨部门403、状态不可接管400）
  } finally {
    taking.value = false
  }
}
</script>

<template>
  <div class="wf-canvas">
    <!-- 图例 -->
    <div class="legend">
      <span class="lg lg-pending">待执行</span>
      <span class="lg lg-running">执行中</span>
      <span class="lg lg-succeeded">完成</span>
      <span class="lg lg-failed">失败</span>
      <span class="lg lg-overridden">人审结果优先</span>
    </div>

    <!-- 加载失败态 -->
    <div v-if="loadFailed" class="load-failed">
      <span>轨迹加载失败</span>
      <el-button size="small" @click="startPolling">重试</el-button>
    </div>

    <!-- 骨架（首帧未返回） -->
    <div v-else-if="!nodes.length" class="skeleton">
      <el-skeleton :rows="1" animated />
    </div>

    <!-- 画布主体：4列 + 列间箭头 -->
    <div v-else class="stage">
      <template v-for="(col, ci) in STAGE_COLUMNS" :key="ci">
        <div :class="['col', { parallel: col.length > 1 }]">
          <el-tooltip
            v-for="name in col"
            :key="name"
            placement="top"
            :disabled="!byNode(name) || byNode(name)!.status === 'pending'"
          >
            <template #content>
              <div class="tip">{{ nodeTip(byNode(name)) }}</div>
            </template>
            <div :class="['node-box', byNode(name)?.status || 'pending']">
              <div class="node-head">
                <el-icon
                  :class="{ 'is-loading': byNode(name)?.status === 'running' }"
                >
                  <component :is="STATUS_ICON[byNode(name)?.status || 'pending']" />
                </el-icon>
                <span class="node-label">{{ byNode(name)?.label || name }}</span>
              </div>
              <div v-if="byNode(name)?.status === 'overridden'" class="node-badge">
                人审结果优先
              </div>
              <div v-else class="node-status">
                {{ STATUS_TAG[byNode(name)?.status || 'pending'] }}
              </div>
              <div v-if="byNode(name)?.error" class="node-error" :title="byNode(name)!.error!">
                {{ byNode(name)!.error }}
              </div>
            </div>
          </el-tooltip>
        </div>
        <div v-if="ci < STAGE_COLUMNS.length - 1" class="arrow" />
      </template>
    </div>

    <!-- 运行提示 -->
    <div v-if="hasRunning" class="running-hint">
      <el-icon class="is-loading"><Loading /></el-icon>
      AI 审核执行中…（约2-3分钟，节点完成后逐个点亮）
    </div>

    <!-- 断点恢复重跑（卡死/失败单的续跑入口） -->
    <div v-if="canRetry" class="retry-bar">
      <span class="retry-label">未完成或中断的审核可断点续跑：已完成节点直接复用，不重复调用AI</span>
      <el-button type="primary" size="small" plain :loading="retrying" @click="doRetry">
        重新执行
      </el-button>
    </div>

    <!-- 人工接管 -->
    <div v-if="canTakeover" class="takeover-bar">
      <span class="takeover-label">人工接管（人审优先）：可随时直接裁决，AI 结论将以人工结果为准</span>
      <el-button type="success" size="small" :loading="taking" @click="doTakeover('approve')">
        批准
      </el-button>
      <el-button type="danger" size="small" :loading="taking" @click="doTakeover('reject')">
        驳回
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.wf-canvas {
  .legend {
    display: flex;
    gap: 14px;
    margin-bottom: 10px;

    .lg {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
      color: #909399;

      &::before {
        content: '';
        width: 10px;
        height: 10px;
        border-radius: 2px;
        border: 1.5px solid #c0c4cc;
      }

      &.lg-running::before {
        border-color: #409eff;
        background: #ecf5ff;
      }

      &.lg-succeeded::before {
        border-color: #67c23a;
        background: #f0f9eb;
      }

      &.lg-failed::before {
        border-color: #f56c6c;
        background: #fef0f0;
      }

      &.lg-overridden::before {
        border-color: #a855f7;
        background: #faf5ff;
      }
    }
  }

  .stage {
    display: flex;
    align-items: center;
    gap: 4px;
    overflow-x: auto;
    padding: 14px 4px;

    .col {
      display: flex;
      flex-direction: column;
      gap: 10px;

      &.parallel {
        gap: 14px;
      }
    }

    // 列间箭头：横线+三角
    .arrow {
      flex: none;
      width: 26px;
      height: 2px;
      background: #c0c4cc;
      position: relative;
      margin: 0 2px;

      &::after {
        content: '';
        position: absolute;
        right: -1px;
        top: 50%;
        transform: translateY(-50%);
        border: 5px solid transparent;
        border-left-color: #c0c4cc;
      }
    }
  }

  .node-box {
    min-width: 104px;
    max-width: 150px;
    padding: 8px 12px;
    border: 1.5px solid #dcdfe6;
    border-radius: 8px;
    background: #fafafa;
    text-align: center;

    .node-head {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;

      .node-label {
        font-size: 13px;
        font-weight: 600;
        color: #606266;
        white-space: nowrap;
      }
    }

    .node-status {
      margin-top: 3px;
      font-size: 11px;
      color: #909399;
    }

    .node-error {
      margin-top: 3px;
      font-size: 11px;
      color: #f56c6c;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    &.running {
      border-color: #409eff;
      background: #ecf5ff;

      .node-label { color: #409eff; }
      .node-status { color: #409eff; }
    }

    &.succeeded {
      border-color: #67c23a;
      background: #f0f9eb;

      .node-label { color: #67c23a; }
      .node-status { color: #67c23a; }
    }

    &.failed {
      border-color: #f56c6c;
      background: #fef0f0;

      .node-label { color: #f56c6c; }
      .node-status { color: #f56c6c; }
    }

    &.overridden {
      border: 2px dashed #a855f7;
      background: #faf5ff;

      .node-label { color: #a855f7; }
      .node-badge {
        margin-top: 3px;
        font-size: 11px;
        color: #a855f7;
        font-weight: 600;
      }
    }
  }

  .running-hint {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
    font-size: 12px;
    color: #409eff;
  }

  .load-failed {
    display: flex;
    align-items: center;
    gap: 10px;
    color: #909399;
    font-size: 13px;
    padding: 8px 0;
  }

  .skeleton {
    padding: 8px 0;
  }

  .takeover-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 12px;
    padding: 10px 12px;
    background: #fdf6ec;
    border: 1px dashed #e6a23c;
    border-radius: 6px;

    .takeover-label {
      flex: 1;
      min-width: 200px;
      font-size: 12px;
      color: #b88230;
    }
  }

  .retry-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 12px;
    padding: 10px 12px;
    background: #ecf5ff;
    border: 1px dashed #409eff;
    border-radius: 6px;

    .retry-label {
      flex: 1;
      min-width: 200px;
      font-size: 12px;
      color: #3375b9;
    }
  }
}

.tip {
  max-width: 320px;
  white-space: pre-wrap;
  line-height: 1.6;
}
</style>
