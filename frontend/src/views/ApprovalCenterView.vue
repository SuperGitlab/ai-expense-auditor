<script setup lang="ts">
// 审批中心：AI执行中队列 + 两级队列（待经理初审/待财务终审）+ 通过/驳回对话框 + 详情抽屉
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ExpenseDetailDrawer from '@/components/ExpenseDetailDrawer.vue'
import { useClientPagination } from '@/composables/useClientPagination'
import { decideApproval, listPending, listRunning, takeoverDecision } from '@/api/approval'
import { RISK_MAP, formatAmount } from '@/constants'
import { useUserStore } from '@/stores/user'
import type { PendingExpense } from '@/types'

const loading = ref(false)
const items = ref<PendingExpense[]>([])
const runningItems = ref<PendingExpense[]>([])
const activeTab = ref('running')

// 角色显隐：初审按钮 manager/admin；终审按钮 finance/admin；接管按钮三角色皆可
const userStore = useUserStore()
const role = computed(() => userStore.role)
const canDecide = (status: string) =>
  status === 'pending'
    ? ['manager', 'admin'].includes(role.value)
    : ['finance', 'admin'].includes(role.value)
const pendingItems = computed(() => items.value.filter((i) => i.status === 'pending'))
const finalItems = computed(() => items.value.filter((i) => i.status === 'manager_approved'))

// 三个队列全量加载+前端分页（15秒刷新替换数组时页码保持，行数减少自动收回越界页码）
const {
  page: runningPage,
  pageSize: runningPageSize,
  paged: pagedRunningItems,
} = useClientPagination(runningItems)
const {
  page: firstPage,
  pageSize: firstPageSize,
  paged: pagedPendingItems,
} = useClientPagination(pendingItems)
const {
  page: finalPage,
  pageSize: finalPageSize,
  paged: pagedFinalItems,
} = useClientPagination(finalItems)

// 详情抽屉
const drawerVisible = ref(false)
const drawerExpenseId = ref<number | null>(null)

// 审批对话框（mode=takeover 时走人工接管接口：AI执行中的单直接裁决，人审优先）
const decideDialog = reactive({
  visible: false,
  expense: null as PendingExpense | null,
  action: 'approve' as 'approve' | 'reject',
  mode: 'decide' as 'decide' | 'takeover',
  comment: '',
})
const deciding = ref(false)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [pending, running] = await Promise.all([listPending(), listRunning()])
    items.value = pending
    runningItems.value = running
    // 默认停在有内容的栏位：执行中有单看执行中，否则看待初审
    if (activeTab.value === 'running' && !running.length) activeTab.value = 'first'
  } finally {
    if (!silent) loading.value = false
  }
}

function openDetail(row: PendingExpense) {
  drawerExpenseId.value = row.id
  drawerVisible.value = true
}

function openDecide(row: PendingExpense, action: 'approve' | 'reject', mode: 'decide' | 'takeover' = 'decide') {
  decideDialog.expense = row
  decideDialog.action = action
  decideDialog.mode = mode
  decideDialog.comment = ''
  decideDialog.visible = true
}

async function confirmDecide() {
  if (!decideDialog.expense) return
  if (decideDialog.action === 'reject' && !decideDialog.comment.trim()) {
    ElMessage.warning('驳回时必须填写审批意见')
    return
  }
  deciding.value = true
  try {
    const decide = decideDialog.mode === 'takeover' ? takeoverDecision : decideApproval
    await decide(
      decideDialog.expense.id,
      decideDialog.action,
      decideDialog.comment.trim() || undefined,
    )
    ElMessage.success(decideDialog.action === 'approve' ? '已通过' : '已驳回')
    decideDialog.visible = false
    load()
  } catch {
    // 拦截器已提示
  } finally {
    deciding.value = false
  }
}

function formatTime(t: string | null | undefined): string {
  return t ? t.replace('T', ' ').slice(0, 19) : '-'
}

// 15秒静默刷新：AI审核完成后单据自动从「AI 审核中」流转到初审/终审/已完结
let refreshTimer: number | undefined
onMounted(() => {
  load()
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') load(true)
  }, 15000)
})
onUnmounted(() => window.clearInterval(refreshTimer))
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>审批中心</h2>
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>&nbsp;刷新
      </el-button>
    </div>

    <el-card shadow="never">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="mb-12"
        title="审批流水线：AI 审核中 → 经理初审（本部门）→ 财务终审。列表 15 秒自动刷新，AI 审完后单据自动流转到下一栏。AI 尚未审完的单据也可「接管」直接裁决（人审优先，AI 之后的结论只留档不生效）；无经理的部门已自动跳过初审。"
      />

      <el-tabs v-model="activeTab">
        <el-tab-pane :label="`AI 审核中（${runningItems.length}）`" name="running">
          <el-table v-loading="loading" :data="pagedRunningItems" stripe>
            <el-table-column prop="expense_no" label="单号" width="215" />
            <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
            <el-table-column label="申请人" width="110">
              <template #default="{ row }">{{ row.applicant_name || `用户${row.user_id}` }}</template>
            </el-table-column>
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">
                <span class="amount">¥{{ formatAmount(row.total_amount) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="当前环节" width="110">
              <template #default>
                <el-tag type="warning" size="small">AI 审核中</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="165">
              <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <el-button link type="success" @click="openDecide(row, 'approve', 'takeover')">接管通过</el-button>
                <el-button link type="danger" @click="openDecide(row, 'reject', 'takeover')">接管驳回</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无 AI 审核中的单据" :image-size="80" />
            </template>
          </el-table>
          <div v-if="runningItems.length > runningPageSize" class="pagination-wrap">
            <el-pagination
              v-model:current-page="runningPage"
              v-model:page-size="runningPageSize"
              :total="runningItems.length"
              layout="total, prev, pager, next"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`待经理初审（${pendingItems.length}）`" name="first">
          <el-table v-loading="loading" :data="pagedPendingItems" stripe>
            <el-table-column prop="expense_no" label="单号" width="215" />
            <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
            <el-table-column label="申请人" width="110">
              <template #default="{ row }">{{ row.applicant_name || `用户${row.user_id}` }}</template>
            </el-table-column>
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">
                <span class="amount">¥{{ formatAmount(row.total_amount) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="AI 风险" width="110">
              <template #default="{ row }">
                <el-tag
                  v-if="row.risk_level"
                  :type="RISK_MAP[row.risk_level]?.type || 'info'"
                  size="small"
                >
                  {{ RISK_MAP[row.risk_level]?.label || row.risk_level }} {{ row.risk_score }}
                </el-tag>
                <span v-else style="color: #c0c4cc">未审核</span>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="165">
              <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <template v-if="canDecide('pending')">
                  <el-button link type="success" @click="openDecide(row, 'approve')">通过</el-button>
                  <el-button link type="danger" @click="openDecide(row, 'reject')">驳回</el-button>
                </template>
                <span v-else class="wait-hint">等待经理初审</span>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无待初审单据" :image-size="80" />
            </template>
          </el-table>
          <div v-if="pendingItems.length > firstPageSize" class="pagination-wrap">
            <el-pagination
              v-model:current-page="firstPage"
              v-model:page-size="firstPageSize"
              :total="pendingItems.length"
              layout="total, prev, pager, next"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`待财务终审（${finalItems.length}）`" name="final">
          <el-table v-loading="loading" :data="pagedFinalItems" stripe>
            <el-table-column prop="expense_no" label="单号" width="215" />
            <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
            <el-table-column label="申请人" width="110">
              <template #default="{ row }">{{ row.applicant_name || `用户${row.user_id}` }}</template>
            </el-table-column>
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">
                <span class="amount">¥{{ formatAmount(row.total_amount) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="AI 风险" width="110">
              <template #default="{ row }">
                <el-tag
                  v-if="row.risk_level"
                  :type="RISK_MAP[row.risk_level]?.type || 'info'"
                  size="small"
                >
                  {{ RISK_MAP[row.risk_level]?.label || row.risk_level }} {{ row.risk_score }}
                </el-tag>
                <span v-else style="color: #c0c4cc">未审核</span>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="165">
              <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <template v-if="canDecide('manager_approved')">
                  <el-button link type="success" @click="openDecide(row, 'approve')">通过</el-button>
                  <el-button link type="danger" @click="openDecide(row, 'reject')">驳回</el-button>
                </template>
                <span v-else class="wait-hint">等待财务终审</span>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无待终审单据" :image-size="80" />
            </template>
          </el-table>
          <div v-if="finalItems.length > finalPageSize" class="pagination-wrap">
            <el-pagination
              v-model:current-page="finalPage"
              v-model:page-size="finalPageSize"
              :total="finalItems.length"
              layout="total, prev, pager, next"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 审批对话框 -->
    <el-dialog
      v-model="decideDialog.visible"
      :title="
        decideDialog.mode === 'takeover'
          ? decideDialog.action === 'approve' ? '接管通过（人审优先）' : '接管驳回（人审优先）'
          : decideDialog.action === 'approve' ? '审批通过' : '审批驳回'
      "
      width="460px"
    >
      <div class="decide-info">
        <span>{{ decideDialog.expense?.expense_no }}</span>
        <span class="amount">¥{{ formatAmount(decideDialog.expense?.total_amount) }}</span>
      </div>
      <el-input
        v-model="decideDialog.comment"
        type="textarea"
        :rows="3"
        :placeholder="decideDialog.action === 'reject' ? '驳回原因（必填）' : '审批意见（选填）'"
      />
      <template #footer>
        <el-button @click="decideDialog.visible = false">取消</el-button>
        <el-button
          :type="decideDialog.action === 'approve' ? 'success' : 'danger'"
          :loading="deciding"
          @click="confirmDecide"
        >
          {{ decideDialog.action === 'approve' ? '确认通过' : '确认驳回' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 详情抽屉 -->
    <ExpenseDetailDrawer v-model:visible="drawerVisible" :expense-id="drawerExpenseId" />
  </div>
</template>

<style scoped lang="scss">
.mb-12 {
  margin-bottom: 12px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.decide-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
  color: #606266;
}

.wait-hint {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
