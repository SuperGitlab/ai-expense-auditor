<script setup lang="ts">
// 数据报表（finance/admin）：总览卡片 + 状态分布 + 月度趋势(CSS柱图) + 分类占比
import { computed, onMounted, ref } from 'vue'
import { getByCategory, getSummary, getTrends, exportReport } from '@/api/report'
import { STATUS_MAP, formatAmount } from '@/constants'
import type { CategoryStat, ReportSummary, TrendMonth } from '@/types'

const loading = ref(true)
const summary = ref<ReportSummary | null>(null)
const trends = ref<TrendMonth[]>([])
const categories = ref<CategoryStat[]>([])

// 趋势柱图：金额按最大值归一化为柱高
const maxTrendAmount = computed(() =>
  Math.max(1, ...trends.value.map((t) => t.amount)),
)

const totalCategoryAmount = computed(() =>
  categories.value.reduce((s, c) => s + c.amount, 0),
)

async function load() {
  loading.value = true
  try {
    const [s, t, c] = await Promise.all([getSummary(), getTrends(6), getByCategory()])
    summary.value = s
    trends.value = t.months
    categories.value = c.categories
  } finally {
    loading.value = false
  }
}

const exporting = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    await exportReport(6)
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container" v-loading="loading">
    <div class="page-header">
      <h2>数据报表</h2>
      <el-button type="success" :loading="exporting" @click="handleExport">
        <el-icon><Download /></el-icon>&nbsp;导出 Excel
      </el-button>
      <el-button @click="load"><el-icon><Refresh /></el-icon>&nbsp;刷新</el-button>
    </div>

    <!-- 总览卡片 -->
    <div class="stat-row" v-if="summary">
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

    <el-row :gutter="16">
      <!-- 月度趋势 -->
      <el-col :span="14">
        <el-card shadow="never" class="chart-card">
          <template #header>近 6 个月趋势（柱高=金额，右侧=单数）</template>
          <div v-if="trends.length" class="trend-chart">
            <div v-for="t in trends" :key="t.month" class="trend-row">
              <div class="trend-month">{{ t.month }}</div>
              <div class="trend-bar-track">
                <div
                  class="trend-bar"
                  :style="{ width: `${Math.max(2, (t.amount / maxTrendAmount) * 100)}%` }"
                >
                  <span class="trend-amount">¥{{ formatAmount(t.amount) }}</span>
                </div>
              </div>
              <div class="trend-count">{{ t.count }} 单</div>
            </div>
          </div>
          <el-empty v-else description="暂无数据" :image-size="70" />
        </el-card>
      </el-col>

      <!-- 状态分布 -->
      <el-col :span="10">
        <el-card shadow="never" class="chart-card">
          <template #header>各状态分布</template>
          <div class="status-list" v-if="summary">
            <div v-for="(count, status) in summary.by_status" :key="status" class="status-item">
              <el-tag :type="STATUS_MAP[status]?.type || 'info'">
                {{ STATUS_MAP[status]?.label || status }}
              </el-tag>
              <span class="status-count">{{ count }} 单</span>
            </div>
            <el-empty
              v-if="!Object.keys(summary.by_status).length"
              description="暂无数据"
              :image-size="70"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 分类占比 -->
    <el-card shadow="never" class="chart-card">
      <template #header>费用分类占比（累计 ¥{{ formatAmount(totalCategoryAmount) }}）</template>
      <el-table v-if="categories.length" :data="categories" stripe>
        <el-table-column prop="name" label="费用类别" min-width="140" />
        <el-table-column label="金额" width="140" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ formatAmount(row.amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="count" label="笔数" width="90" align="center" />
        <el-table-column label="占比" min-width="240">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round(row.ratio * 1000) / 10"
              :stroke-width="14"
              :format="(p: number) => `${p}%`"
            />
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无数据" :image-size="70" />
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.chart-card {
  margin-bottom: 16px;
}

.trend-chart {
  display: flex;
  flex-direction: column;
  gap: 10px;

  .trend-row {
    display: flex;
    align-items: center;
    gap: 12px;

    .trend-month {
      width: 64px;
      color: #606266;
      font-size: 13px;
    }

    .trend-bar-track {
      flex: 1;
      background: #f0f2f5;
      border-radius: 4px;

      .trend-bar {
        min-width: 90px;
        background: linear-gradient(90deg, #79bbff, #409eff);
        border-radius: 4px;
        padding: 6px 10px;
        transition: width 0.4s ease;

        .trend-amount {
          color: #fff;
          font-size: 12px;
          white-space: nowrap;
        }
      }
    }

    .trend-count {
      width: 56px;
      text-align: right;
      color: #909399;
      font-size: 13px;
    }
  }
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: 12px;

  .status-item {
    display: flex;
    align-items: center;
    justify-content: space-between;

    .status-count {
      color: #606266;
      font-weight: 600;
    }
  }
}
</style>
