<script setup lang="ts">
// 工作台：统计卡片（角色差异化）+ 最近报销单
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listExpenses } from '@/api/expense'
import { getSummary } from '@/api/report'
import { useUserStore } from '@/stores/user'
import { EXPENSE_TYPE_MAP, STATUS_MAP, formatAmount } from '@/constants'
import type { Expense, ReportSummary } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const summary = ref<ReportSummary | null>(null)
const recent = ref<Expense[]>([])
// 普通角色的自算统计（无报表权限时用列表接口的total凑）
const myStats = ref({ total: 0, draft: 0, waiting: 0, approved: 0 })

const isReporter = computed(() => userStore.canReport)

async function loadReporterData() {
  const [summaryRes, recentRes] = await Promise.all([
    getSummary(),
    listExpenses({ page: 1, page_size: 5 }),
  ])
  summary.value = summaryRes
  recent.value = recentRes.items
}

async function loadEmployeeData() {
  // 并行查4种状态的total（page_size=1只要计数）
  const [all, draft, submitted, pending, approved, recentRes] = await Promise.all([
    listExpenses({ page: 1, page_size: 1 }),
    listExpenses({ page: 1, page_size: 1, status: 'draft' }),
    listExpenses({ page: 1, page_size: 1, status: 'submitted' }),
    listExpenses({ page: 1, page_size: 1, status: 'pending' }),
    listExpenses({ page: 1, page_size: 1, status: 'approved' }),
    listExpenses({ page: 1, page_size: 5 }),
  ])
  myStats.value = {
    total: all.total,
    draft: draft.total,
    waiting: submitted.total + pending.total,
    approved: approved.total,
  }
  recent.value = recentRes.items
}

onMounted(async () => {
  try {
    if (isReporter.value) {
      await loadReporterData()
    } else {
      await loadEmployeeData()
    }
  } finally {
    loading.value = false
  }
})

function goSubmit() {
  router.push('/expenses/new')
}
</script>

<template>
  <div class="page-container" v-loading="loading">
    <div class="page-header">
      <h2>你好，{{ userStore.displayName }}（{{ userStore.roleLabel }}）</h2>
      <el-button type="primary" @click="goSubmit">
        <el-icon><Plus /></el-icon>&nbsp;提交报销
      </el-button>
    </div>

    <!-- 统计卡片：finance/admin看全局，其他角色看自己的 -->
    <div class="stat-row" v-if="isReporter && summary">
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">报销单总数</div>
        <div class="stat-value">{{ summary.total }}</div>
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">本月新增</div>
        <div class="stat-value">{{ summary.month_count }}</div>
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">累计报销金额</div>
        <div class="stat-value">
          {{ formatAmount(summary.total_amount) }}<span class="stat-unit">元</span>
        </div>
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">平均风险分</div>
        <div class="stat-value">{{ summary.avg_risk_score }}</div>
      </el-card>
    </div>
    <div class="stat-row" v-else>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">我的报销单</div>
        <div class="stat-value">{{ myStats.total }}</div>
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">草稿箱</div>
        <div class="stat-value">{{ myStats.draft }}</div>
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">审核中</div>
        <div class="stat-value">{{ myStats.waiting }}</div>
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <div class="stat-label">已通过</div>
        <div class="stat-value">{{ myStats.approved }}</div>
      </el-card>
    </div>

    <!-- 状态分布（仅报表角色） -->
    <el-card v-if="isReporter && summary" shadow="never" class="section-card">
      <template #header>各状态单据分布</template>
      <div class="status-row">
        <template v-for="(count, status) in summary.by_status" :key="status">
          <el-tag v-if="STATUS_MAP[status]" :type="STATUS_MAP[status].type" size="large">
            {{ STATUS_MAP[status].label }}：{{ count }}
          </el-tag>
        </template>
      </div>
    </el-card>

    <!-- 最近报销单 -->
    <el-card shadow="never" class="section-card">
      <template #header>最近报销单</template>
      <el-table :data="recent" stripe>
        <el-table-column prop="expense_no" label="单号" width="220" />
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ EXPENSE_TYPE_MAP[row.expense_type] || row.expense_type }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ formatAmount(row.total_amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="STATUS_MAP[row.status]?.type || 'info'">
              {{ STATUS_MAP[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.risk_level" :type="row.risk_level === 'low' ? 'success' : row.risk_level === 'high' ? 'danger' : 'warning'" size="small">
              {{ row.risk_score }}分
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push('/expenses')">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.section-card {
  margin-bottom: 16px;
}

.status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
</style>
