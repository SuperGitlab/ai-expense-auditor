<script setup lang="ts">
// 我的报销列表：筛选 + 状态/风险标签 + 提交/编辑/取消/删除 + 详情抽屉
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import ExpenseDetailDrawer from '@/components/ExpenseDetailDrawer.vue'
import {
  cancelExpense,
  deleteExpense,
  listExpenses,
  payExpense,
  submitExpense,
  triggerAIReview,
} from '@/api/expense'
import { useUserStore } from '@/stores/user'
import {
  EXPENSE_TYPE_MAP,
  RISK_MAP,
  STATUS_MAP,
  formatAmount,
} from '@/constants'
import type { Expense, ExpenseStatus, ExpenseType } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const items = ref<Expense[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 10,
  status: null as ExpenseStatus | null,
  expense_type: null as ExpenseType | null,
})

// 详情抽屉
const drawerVisible = ref(false)
const drawerExpenseId = ref<number | null>(null)

// 重新AI审核（走真实LLM，可能耗时数十秒）
const reviewingId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await listExpenses(query)
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function openDetail(row: Expense) {
  drawerExpenseId.value = row.id
  drawerVisible.value = true
}

async function handleSubmit(row: Expense) {
  await ElMessageBox.confirm(
    '提交后将自动触发 AI 审核（低风险自动通过，中高风险转人工），确定提交？',
    '提交确认',
    { type: 'info' },
  )
  await submitExpense(row.id)
  // 后端AI审核异步执行，这里秒回；结果等审核完成后刷新可见
  ElMessage.success('已提交，AI 审核进行中，请稍后刷新查看结果')
  load()
}

async function handleCancel(row: Expense) {
  await ElMessageBox.confirm('确定取消该报销单？取消后不可恢复。', '取消确认', { type: 'warning' })
  await cancelExpense(row.id)
  ElMessage.success('已取消')
  load()
}

async function handleDelete(row: Expense) {
  await ElMessageBox.confirm('确定删除该报销单？删除后不可恢复。', '删除确认', { type: 'warning' })
  await deleteExpense(row.id)
  ElMessage.success('已删除')
  load()
}

async function handleReReview(row: Expense) {
  await ElMessageBox.confirm(
    'AI复审将重新执行完整AI审核（真实调用大模型，约需数十秒），并可能更新风险等级与审核结论。确定发起？',
    'AI复审确认',
    { type: 'warning' },
  )
  reviewingId.value = row.id
  try {
    const result = await triggerAIReview(row.id)
    ElMessage.success(
      `AI审核完成：${RISK_MAP[result.risk_level]?.label || result.risk_level} ${result.risk_score}分 → ${result.decision}`,
    )
    load()
  } catch {
    // 拦截器已提示（常见：状态不允许审核）
  } finally {
    reviewingId.value = null
  }
}

// 本人或finance/admin可手动触发AI复审
function canReReview(row: Expense): boolean {
  if (!['submitted', 'pending'].includes(row.status)) return false
  const role = userStore.user?.role
  return role === 'admin' || role === 'finance' || row.user_id === userStore.user?.id
}

async function handlePay(row: Expense) {
  await ElMessageBox.confirm(
    '请确认已在网银/财务系统完成转账。登记后单据状态将变为「已支付」。',
    '打款登记',
    { type: 'warning' },
  )
  await payExpense(row.id)
  ElMessage.success('已登记打款')
  load()
}

function formatTime(t: string | null | undefined): string {
  return t ? t.replace('T', ' ').slice(0, 19) : '-'
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>我的报销</h2>
      <el-button type="primary" @click="router.push('/expenses/new')">
        <el-icon><Plus /></el-icon>&nbsp;新建报销
      </el-button>
    </div>

    <el-card shadow="never">
      <!-- 筛选栏 -->
      <div class="table-toolbar">
        <div class="filters">
          <el-select
            v-model="query.status"
            placeholder="全部状态"
            clearable
            style="width: 140px"
            @change="search"
          >
            <el-option
              v-for="(meta, value) in STATUS_MAP"
              :key="value"
              :label="meta.label"
              :value="value"
            />
          </el-select>
          <el-select
            v-model="query.expense_type"
            placeholder="全部类型"
            clearable
            style="width: 140px"
            @change="search"
          >
            <el-option
              v-for="(label, value) in EXPENSE_TYPE_MAP"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </div>
      </div>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="expense_no" label="单号" width="215" />
        <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
        <el-table-column label="类型" width="85">
          <template #default="{ row }">
            {{ EXPENSE_TYPE_MAP[row.expense_type] || row.expense_type }}
          </template>
        </el-table-column>
        <el-table-column label="金额" width="110" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ formatAmount(row.total_amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="92">
          <template #default="{ row }">
            <el-tag :type="STATUS_MAP[row.status]?.type || 'info'">
              {{ STATUS_MAP[row.status]?.label || row.status }}
            </el-tag>
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
        <el-table-column label="创建时间" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="['draft', 'rejected'].includes(row.status)"
              link
              type="success"
              @click="handleSubmit(row)"
            >
              提交
            </el-button>
            <el-button
              v-if="['draft', 'rejected'].includes(row.status)"
              link
              type="primary"
              @click="router.push(`/expenses/edit/${row.id}`)"
            >
              编辑
            </el-button>
            <el-button
              v-if="canReReview(row)"
              link
              type="warning"
              :loading="reviewingId === row.id"
              @click="handleReReview(row)"
            >
              AI复审
            </el-button>
            <el-button
              v-if="row.status === 'approved' && userStore.canPay"
              link
              type="success"
              @click="handlePay(row)"
            >
              打款
            </el-button>
            <el-button
              v-if="['draft', 'submitted', 'pending'].includes(row.status)"
              link
              type="info"
              @click="handleCancel(row)"
            >
              取消
            </el-button>
            <el-button
              v-if="['draft', 'rejected'].includes(row.status)"
              link
              type="danger"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <ExpenseDetailDrawer v-model:visible="drawerVisible" :expense-id="drawerExpenseId" />
  </div>
</template>

<style scoped lang="scss">
.filters {
  display: flex;
  gap: 8px;
}
</style>
