<script setup lang="ts">
// 报销单详情抽屉：基本信息 + 明细 + AI审核结果 + 审批时间线
import { computed, ref, watch } from 'vue'
import { getApprovalHistory } from '@/api/approval'
import { getExpense } from '@/api/expense'
import {
  AI_DECISION_MAP,
  EXPENSE_TYPE_MAP,
  RISK_MAP,
  STATUS_MAP,
  formatAmount,
} from '@/constants'
import type { ApprovalRecord, Expense } from '@/types'

const props = defineProps<{ visible: boolean; expenseId: number | null }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void }>()

const loading = ref(false)
const expense = ref<Expense | null>(null)
const history = ref<ApprovalRecord[]>([])

const drawerVisible = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const riskInfo = computed(() => {
  if (!expense.value?.risk_level) return null
  return RISK_MAP[expense.value.risk_level] || null
})

// ===== AI审核结果结构化展示 =====
// 后端把review_result用json.dumps存成字符串，这里解析后按结构渲染；
// 解析失败（旧数据/纯文本）返回null，模板走原样展示兜底
interface ReviewViolation {
  rule_code: string
  rule_name: string
  severity: 'block' | 'warn' | string
  risk_points: number
  detail: string
}
interface AIReviewDetail {
  reason: string
  suggestions?: string[]
  rule_violations?: ReviewViolation[]
  document_anomalies?: string[]
  llm_suggestion?: string | null
  risk_factors?: string[]
}

// 违规严重度 → 标签样式（block=阻断红 / warn=警告橙）
const SEVERITY_MAP: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  block: { label: '阻断', type: 'danger' },
  warn: { label: '警告', type: 'warning' },
}

const aiReview = computed<AIReviewDetail | null>(() => {
  const raw = expense.value?.ai_review_result
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as AIReviewDetail
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
})

const violationsText = computed(() =>
  (aiReview.value?.rule_violations || []).map((v) => v.detail).join(' '),
)

// 后端各字段内容高度重复（suggestions/risk_factors常与violations逐字相同），
// 过滤掉已在reason或违规明细里出现过的，避免同一条信息刷三遍
function filterCovered(list: string[] | undefined, ...covered: (string | undefined)[]): string[] {
  if (!list?.length) return []
  const haystack = covered.filter(Boolean).join(' ')
  return list.filter((s) => s && !haystack.includes(s))
}

const extraSuggestions = computed(() =>
  filterCovered(aiReview.value?.suggestions, aiReview.value?.reason, violationsText.value),
)
const extraAnomalies = computed(() =>
  filterCovered(aiReview.value?.document_anomalies, aiReview.value?.reason, violationsText.value),
)
const extraFactors = computed(() =>
  filterCovered(aiReview.value?.risk_factors, aiReview.value?.reason, violationsText.value),
)

async function load(expenseId: number) {
  loading.value = true
  try {
    const [exp, hist] = await Promise.all([
      getExpense(expenseId),
      getApprovalHistory(expenseId),
    ])
    expense.value = exp
    history.value = hist.items
  } finally {
    loading.value = false
  }
}

// 打开时按expenseId加载（同一抽屉可切换不同单据）
watch(
  () => [props.visible, props.expenseId] as const,
  ([visible, id]) => {
    if (visible && id) {
      expense.value = null
      history.value = []
      load(id)
    }
  },
)

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    submit: '提交报销',
    ai_review: 'AI 审核',
    approve: '审批通过',
    reject: '审批驳回',
  }
  return map[action] || action
}

function formatTime(t: string | null | undefined): string {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}
</script>

<template>
  <el-drawer v-model="drawerVisible" title="报销单详情" size="640px">
    <div v-loading="loading">
      <template v-if="expense">
        <!-- 基本信息 -->
        <el-descriptions :column="2" border size="small" class="section">
          <el-descriptions-item label="单号" :span="2">{{ expense.expense_no }}</el-descriptions-item>
          <el-descriptions-item label="标题" :span="2">{{ expense.title }}</el-descriptions-item>
          <el-descriptions-item label="类型">
            {{ EXPENSE_TYPE_MAP[expense.expense_type] || expense.expense_type }}
          </el-descriptions-item>
          <el-descriptions-item label="金额">
            <span class="amount">¥{{ formatAmount(expense.total_amount) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="STATUS_MAP[expense.status]?.type || 'info'">
              {{ STATUS_MAP[expense.status]?.label || expense.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatTime(expense.submitted_at) }}</el-descriptions-item>
          <el-descriptions-item label="说明" :span="2">{{ expense.description || '-' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 驳回原因 -->
        <el-alert
          v-if="expense.status === 'rejected' && expense.rejection_reason"
          class="section"
          type="error"
          :closable="false"
          show-icon
          :title="'驳回原因：' + expense.rejection_reason"
        />

        <!-- 费用明细 -->
        <div class="section-title">费用明细</div>
        <el-table :data="expense.items" border size="small" class="section">
          <el-table-column prop="description" label="说明" min-width="140" show-overflow-tooltip />
          <el-table-column label="金额" width="100" align="right">
            <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
          </el-table-column>
          <el-table-column prop="expense_date" label="日期" width="105" />
          <el-table-column label="发票号" width="130">
            <template #default="{ row }">
              <el-tag v-if="row.invoice_no" size="small" type="success">{{ row.invoice_no }}</el-tag>
              <el-tag v-else size="small" type="danger">无发票</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- AI 审核结果 -->
        <div class="section-title">AI 审核结果</div>
        <el-card v-if="expense.risk_level" shadow="never" class="section">
          <div class="risk-row">
            <el-tag :type="riskInfo?.type || 'info'" size="large">{{ riskInfo?.label || expense.risk_level }}</el-tag>
            <div class="risk-progress">
              <el-progress
                :percentage="Math.round(Number(expense.risk_score) || 0)"
                :color="riskInfo?.color"
                :stroke-width="14"
                :format="(p: number) => `${p} 分`"
              />
            </div>
          </div>
          <!-- 结构化展示：结论 + 规则命中明细 + 去重后的补充信息 -->
          <template v-if="aiReview">
            <div class="ai-reason">{{ aiReview.reason || '（AI 未生成说明）' }}</div>

            <div
              v-for="(v, i) in aiReview.rule_violations"
              :key="i"
              class="violation-item"
            >
              <el-tag :type="SEVERITY_MAP[v.severity]?.type || 'info'" size="small">
                {{ SEVERITY_MAP[v.severity]?.label || v.severity }}
              </el-tag>
              <span class="violation-name">{{ v.rule_name }}</span>
              <span class="violation-detail">{{ v.detail }}</span>
              <span class="violation-points">+{{ v.risk_points }}分</span>
            </div>

            <div v-if="extraAnomalies.length" class="tag-row">
              <span class="tag-row-label">单据异常</span>
              <el-tag v-for="(a, i) in extraAnomalies" :key="i" size="small" type="danger" effect="plain">
                {{ a }}
              </el-tag>
            </div>
            <div v-if="extraFactors.length" class="tag-row">
              <span class="tag-row-label">风险因素</span>
              <el-tag v-for="(f, i) in extraFactors" :key="i" size="small" type="warning" effect="plain">
                {{ f }}
              </el-tag>
            </div>
            <template v-if="extraSuggestions.length">
              <div class="tag-row">
                <span class="tag-row-label">处理建议</span>
              </div>
              <ul class="suggestion-list">
                <li v-for="(s, i) in extraSuggestions" :key="i">{{ s }}</li>
              </ul>
            </template>
            <div v-if="aiReview.llm_suggestion" class="llm-suggestion">
              {{ aiReview.llm_suggestion }}
            </div>
          </template>
          <!-- 解析失败的旧数据：原样展示兜底 -->
          <div v-else class="ai-result-text">{{ expense.ai_review_result || '（AI 未生成说明）' }}</div>
        </el-card>
        <el-empty v-else description="尚未进行 AI 审核" :image-size="60" class="section" />

        <!-- 审批时间线 -->
        <div class="section-title">审批流程</div>
        <el-timeline class="section timeline">
          <el-timeline-item
            v-for="record in history"
            :key="record.id"
            :timestamp="formatTime(record.created_at)"
            :type="record.action === 'reject' ? 'danger' : record.action === 'approve' ? 'success' : record.action === 'ai_review' ? 'primary' : undefined"
            :hollow="record.action === 'submit'"
          >
            <!-- AI审核行特殊标记 -->
            <div class="timeline-item" :class="{ 'ai-row': record.action === 'ai_review' }">
              <div class="timeline-title">
                <el-icon v-if="record.action === 'ai_review'" color="#409eff"><MagicStick /></el-icon>
                <span>{{ record.approver_name }}</span>
                <span class="timeline-action">{{ actionLabel(record.action) }}</span>
                <el-tag
                  v-if="record.action === 'ai_review' && record.ai_decision"
                  size="small"
                  type="warning"
                >
                  {{ AI_DECISION_MAP[record.ai_decision] || record.ai_decision }}
                </el-tag>
                <el-tag v-if="record.action === 'ai_review' && record.risk_level" size="small">
                  风险 {{ record.risk_score }}分 / {{ RISK_MAP[record.risk_level]?.label || record.risk_level }}
                </el-tag>
              </div>
              <div v-if="record.comment" class="timeline-comment">{{ record.comment }}</div>
            </div>
          </el-timeline-item>
          <el-timeline-item v-if="!history.length" timestamp="-">
            <span style="color: #909399">暂无审批记录</span>
          </el-timeline-item>
        </el-timeline>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped lang="scss">
.section {
  margin-bottom: 16px;
}

.section-title {
  font-weight: 600;
  margin: 18px 0 10px;
  color: #303133;
}

.risk-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;

  .risk-progress {
    flex: 1;
  }
}

.ai-result-text {
  color: #606266;
  line-height: 1.7;
  font-size: 13px;
  white-space: pre-wrap;
}

/* ===== AI审核结果结构化展示 ===== */
.ai-reason {
  color: #303133;
  line-height: 1.7;
  font-size: 13px;
  margin-bottom: 10px;
}

.violation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 6px;
  font-size: 13px;

  .violation-name {
    font-weight: 600;
    color: #303133;
    white-space: nowrap;
  }

  .violation-detail {
    color: #606266;
    flex: 1;
  }

  .violation-points {
    color: #f56c6c;
    font-weight: 600;
    white-space: nowrap;
  }
}

.tag-row {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;

  .tag-row-label {
    color: #909399;
    font-size: 12px;
    line-height: 24px;
  }
}

.suggestion-list {
  margin: 6px 0 0;
  padding-left: 18px;
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}

.llm-suggestion {
  margin-top: 10px;
  padding: 8px 10px;
  background: #ecf5ff;
  border-left: 3px solid #409eff;
  border-radius: 2px;
  color: #303133;
  font-size: 13px;
  line-height: 1.7;
}

.timeline {
  padding-left: 6px;

  .timeline-item {
    &.ai-row .timeline-title {
      color: #409eff;
      font-weight: 600;
    }

    .timeline-title {
      display: flex;
      align-items: center;
      gap: 6px;

      .timeline-action {
        color: #909399;
        font-size: 13px;
      }
    }

    .timeline-comment {
      margin-top: 4px;
      color: #606266;
      font-size: 13px;
      line-height: 1.6;
      white-space: pre-wrap;
    }
  }
}
</style>
