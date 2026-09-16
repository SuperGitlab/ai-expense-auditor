<script setup lang="ts">
// 审批中心：两级队列（待经理初审/待财务终审）+ 通过/驳回对话框 + 详情抽屉
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ExpenseDetailDrawer from '@/components/ExpenseDetailDrawer.vue'
import { decideApproval, listPending } from '@/api/approval'
import { RISK_MAP, formatAmount } from '@/constants'
import { useUserStore } from '@/stores/user'
import type { PendingExpense } from '@/types'

const loading = ref(false)
const items = ref<PendingExpense[]>([])

// 角色显隐：初审按钮 manager/admin；终审按钮 finance/admin
const userStore = useUserStore()
const role = computed(() => userStore.role)
const canDecide = (status: string) =>
  status === 'pending'
    ? ['manager', 'admin'].includes(role.value)
    : ['finance', 'admin'].includes(role.value)
const pendingItems = computed(() => items.value.filter((i) => i.status === 'pending'))
const finalItems = computed(() => items.value.filter((i) => i.status === 'manager_approved'))

// 详情抽屉
const drawerVisible = ref(false)
const drawerExpenseId = ref<number | null>(null)

// 审批对话框
const decideDialog = reactive({
  visible: false,
  expense: null as PendingExpense | null,
  action: 'approve' as 'approve' | 'reject',
  comment: '',
})
const deciding = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = await listPending()
  } finally {
    loading.value = false
  }
}

function openDetail(row: PendingExpense) {
  drawerExpenseId.value = row.id
  drawerVisible.value = true
}

function openDecide(row: PendingExpense, action: 'approve' | 'reject') {
  decideDialog.expense = row
  decideDialog.action = action
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
    await decideApproval(
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

onMounted(load)
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
        title="两级审批：经理初审（本部门）→ 财务终审。此处为 AI 审核后转人工处理的单据；无经理的部门已自动跳过初审。点击「详情」可查看 AI 风险评分、审核说明与节点执行画布——AI 执行中的单据也可在画布上人工接管（人审优先）。"
      />

      <el-tabs model-value="first">
        <el-tab-pane :label="`待经理初审（${pendingItems.length}）`" name="first">
          <el-table v-loading="loading" :data="pendingItems" stripe>
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
        </el-tab-pane>

        <el-tab-pane :label="`待财务终审（${finalItems.length}）`" name="final">
          <el-table v-loading="loading" :data="finalItems" stripe>
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
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 审批对话框 -->
    <el-dialog
      v-model="decideDialog.visible"
      :title="decideDialog.action === 'approve' ? '审批通过' : '审批驳回'"
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
