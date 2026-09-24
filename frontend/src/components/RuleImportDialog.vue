<script setup lang="ts">
// 规则导入对话框（admin）：JSON直导 + 制度文档(docx/pdf)智能导入两通道
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadRequestOptions } from 'element-plus'
import {
  confirmDocumentImport,
  extractDocumentRules,
  getExtractionStatus,
  importRulesJson,
} from '@/api/ruleImport'
import type { DraftRow, ExtractionDraft, ExtractionStatus, RowError } from '@/api/ruleImport'
import RuleDraftTable from '@/components/RuleDraftTable.vue'
import { listCategories } from '@/api/category'
import { listRules } from '@/api/rule'
import { useClientPagination } from '@/composables/useClientPagination'
import { OPERATOR_MAP, RULE_TYPE_MAP, SEVERITY_MAP } from '@/constants'
import type { Category } from '@/types'

const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{ imported: [] }>()

const activeTab = ref<'json' | 'doc'>('json')
const categories = ref<Category[]>([])
const existingCodes = ref<Set<string>>(new Set()) // 库内已有规则代码（"代码已存在"提前标注）
const rowErrors = ref<RowError[]>([]) // 400逐行明细（两通道共用渲染）
const {
  page: errPage,
  pageSize: errPageSize,
  paged: pagedRowErrors,
  reset: resetErrPage,
} = useClientPagination(rowErrors)

// 错误明细统一从这里赋值：新一批错误从第1页看起
function setRowErrors(errs: RowError[]) {
  rowErrors.value = errs
  resetErrPage()
}

// ---------- JSON通道 ----------

const jsonText = ref('')
const jsonImporting = ref(false)

// ---------- JSON解析 → 可编辑草稿表格（与文档通道同款交互） ----------

// 文件里的原始行（宽松类型：未过后端校验，字段可能缺失/非法）
interface PreviewRow {
  name?: string
  code?: string
  rule_type?: string
  category_code?: string | null
  category_id?: number | null
  field_name?: string
  operator?: string
  threshold?: string | null
  severity?: string
  risk_points?: number
  description?: string | null
  is_active?: boolean
}

const NO_THRESHOLD_OPS = ['exists', 'not_exists']
const jsonParsed = ref<{ meta: string[] } | null>(null) // 摘要（规则行进jsonRows）
const jsonParseError = ref('')
const jsonCountMismatch = ref<number | null>(null) // 文件声明条数≠实际解析条数
const rawJsonOpen = ref<string[]>(['raw']) // 原始JSON折叠面板（文件解析成功后收起）
const jsonRows = ref<DraftRow[]>([]) // 可编辑草稿行（勾选+行内修正）
const {
  page: previewPage,
  pageSize: previewPageSize,
  paged: pagedJsonRows,
  offset: jsonOffset,
  reset: resetJsonPage,
} = useClientPagination(jsonRows)
const checkedJsonCount = computed(() => jsonRows.value.filter((r) => r.selected).length)

// 导入前轻校验（后端行校验的客户端镜像，提前暴露问题省一个来回；权威校验仍在后端）
const rowIssues = computed(() => {
  const codeCounts = new Map<string, number>()
  for (const r of jsonRows.value) {
    if (r.code) codeCounts.set(r.code, (codeCounts.get(r.code) ?? 0) + 1)
  }
  return jsonRows.value.map((r) => {
    const issues: string[] = []
    if (!r.name?.trim()) issues.push('缺少名称')
    if (!r.code?.trim()) issues.push('缺少代码')
    if (!r.field_name) issues.push('缺少字段')
    if (!r.operator) issues.push('缺少操作符')
    if (r.operator && !NO_THRESHOLD_OPS.includes(r.operator) && !(r.threshold ?? '').trim())
      issues.push('缺少阈值')
    if (r.code && (codeCounts.get(r.code) ?? 0) > 1) issues.push('代码重复')
    if (r.code && existingCodes.value.has(r.code)) issues.push('代码已存在')
    if (
      r.category_code &&
      categories.value.length &&
      !categories.value.some((c) => c.code === r.category_code)
    )
      issues.push('类别不存在')
    if (r.rule_type && !(r.rule_type in RULE_TYPE_MAP)) issues.push('类型非法')
    if (r.operator && !(r.operator in OPERATOR_MAP)) issues.push('操作符非法')
    if (r.severity && !(r.severity in SEVERITY_MAP)) issues.push('严重度非法')
    if (typeof r.risk_points !== 'number' || r.risk_points < 0 || r.risk_points > 100)
      issues.push('风险分需0-100')
    return issues
  })
})

function jsonIssueOf(_row: DraftRow, index: number): string[] {
  return rowIssues.value[index] ?? []
}

// 外部JSON行 → 可编辑草稿行：有后端默认值的枚举缺省时补默认（custom/warn），
// operator/field_name必填且无默认：留空并在提示列标注，由用户在表格里补
function normalizeJsonRow(r: PreviewRow): DraftRow {
  const row = {
    name: r.name ?? '',
    code: r.code ?? '',
    rule_type: r.rule_type || 'custom',
    category_code: r.category_code ?? null,
    category_id: r.category_id ?? null,
    field_name: r.field_name ?? '',
    operator: r.operator ?? '',
    threshold: r.threshold ?? '',
    severity: r.severity || 'warn',
    risk_points: typeof r.risk_points === 'number' ? r.risk_points : undefined,
    description: r.description ?? '',
    is_active: r.is_active ?? true,
    quote: '',
    selected: true,
  }
  // 外部文件可能带非法枚举值：运行期原样保留，交给提示列+后端行校验拦截
  return row as unknown as DraftRow
}

// 解析：jsonText是唯一数据源（编辑原始JSON后自动重新解析并重建表格）
function parseJsonPreview(fromFile = false) {
  jsonParseError.value = ''
  jsonParsed.value = null
  jsonCountMismatch.value = null
  jsonRows.value = []
  const text = jsonText.value.trim()
  if (!text) return
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch (e) {
    jsonParseError.value = `JSON 解析失败：${(e as Error).message}。请在下方「原始JSON」中修正，编辑完成后自动重新解析。`
    rawJsonOpen.value = ['raw']
    return
  }
  const rules = Array.isArray(data) ? data : (data as { rules?: unknown })?.rules
  if (!Array.isArray(rules) || !rules.length) {
    jsonParseError.value = '未找到规则数组：需要 [ {...}, {...} ] 或 { "rules": [...] } 格式'
    rawJsonOpen.value = ['raw']
    return
  }
  // metadata摘要（有则展示，帮用户确认选对了文件）
  const meta: string[] = []
  const m = (data as { metadata?: Record<string, unknown> }).metadata
  if (m && typeof m === 'object') {
    if (m.name) meta.push(`规则库《${String(m.name)}》`)
    if (m.version) meta.push(`版本 ${String(m.version)}`)
    if (m.source_document) meta.push(`来源：${String(m.source_document)}`)
    if (m.generated_at) meta.push(`生成于 ${String(m.generated_at)}`)
    if (typeof m.rule_count === 'number' && m.rule_count !== rules.length)
      jsonCountMismatch.value = m.rule_count
  }
  resetJsonPage()
  jsonParsed.value = { meta }
  jsonRows.value = (rules as PreviewRow[]).map(normalizeJsonRow)
  if (fromFile) rawJsonOpen.value = [] // 刚选完文件：收起原始JSON，突出表格
}

// 示例code避开init_db种子规则（如MEAL_500）：照抄示例导入必须能成功，
// 撞种子code会被"有错全拒"语义400回绝
const JSON_EXAMPLE = JSON.stringify(
  [
    {
      name: '餐饮单笔限额500元',
      code: 'MEAL_LIMIT_DEMO',
      rule_type: 'amount_limit',
      category_code: 'meal',
      field_name: 'amount',
      operator: 'gt',
      threshold: '500',
      severity: 'warn',
      risk_points: 15,
      description: '餐饮费单笔超过500元，计入风险分',
    },
  ],
  null,
  2,
)

async function onJsonFileChange(file: UploadFile) {
  if (!file.raw) return
  // 去BOM：带BOM的文本直接JSON.parse会抛错
  jsonText.value = (await file.raw.text()).replace(/^﻿/, '')
  parseJsonPreview(true)
}

async function handleJsonImport() {
  setRowErrors([])
  const picked = jsonRows.value.filter((r) => r.selected)
  if (!picked.length) {
    ElMessage.warning('请至少勾选一条要导入的规则')
    return
  }
  jsonImporting.value = true
  try {
    const payload = picked.map(({ selected: _selected, quote: _quote, ...rule }) => {
      const row = { ...rule } as Record<string, unknown>
      // 风险分非法/缺失时不下发该键，走后端默认值（提示列已标注）
      if (typeof row.risk_points !== 'number') delete row.risk_points
      return row
    })
    const res = await importRulesJson(payload)
    ElMessage.success(`成功导入 ${res.imported} 条规则`)
    emit('imported')
    visible.value = false
  } catch (err) {
    // 拦截器已弹detail toast；这里取逐行明细渲染错误表
    setRowErrors(extractRowErrors(err))
  } finally {
    jsonImporting.value = false
  }
}

function removeJsonRow(index: number) {
  jsonRows.value.splice(index, 1)
}

// ---------- 文档通道（异步：提交秒回task_id，Celery后台抽取，前端轮询取草稿） ----------

const confirming = ref(false)
const draftMeta = ref<ExtractionDraft | null>(null) // sections/stats/source（待确认回传）
const draftRows = ref<DraftRow[]>([]) // 草稿行（带勾选态）
const {
  page: docPage,
  pageSize: docPageSize,
  paged: pagedDraftRows,
  offset: docOffset,
  reset: resetDocPage,
} = useClientPagination(draftRows)

const checkedCount = computed(() => draftRows.value.filter((r) => r.selected).length)

// 文档通道提示=后端轻校验结果（静态，随草稿返回）
function docIssueOf(row: DraftRow): string[] {
  return row.issues
}

// 进行中任务：taskId非空即"上传已受理、草稿未回来"
const TASK_STORE_KEY = 'rule_doc_extract_task' // sessionStorage：关窗/刷新后仍能续接
const GIVE_UP_SECONDS = 900 // 15分钟无结果放弃（大文档后端最多重试一次≈10分钟；到点多为worker没启动）
const POLL_INTERVAL_MS = 5000

const taskId = ref('')
const taskFilename = ref('')
const elapsed = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null

const extracting = computed(() => !!taskId.value)

function fmtElapsed(sec: number): string {
  return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`
}

function stopTimers() {
  if (pollTimer) clearInterval(pollTimer)
  if (elapsedTimer) clearInterval(elapsedTimer)
  pollTimer = elapsedTimer = null
}

function saveTask() {
  sessionStorage.setItem(TASK_STORE_KEY, JSON.stringify({ id: taskId.value, filename: taskFilename.value }))
}

function clearTask() {
  stopTimers()
  taskId.value = ''
  taskFilename.value = ''
  elapsed.value = 0
  sessionStorage.removeItem(TASK_STORE_KEY)
}

async function pollOnce() {
  let st: ExtractionStatus
  try {
    st = await getExtractionStatus(taskId.value)
  } catch {
    return // 瞬时网络错误：等下一轮
  }
  const name = taskFilename.value
  if (st.state === 'SUCCESS' && st.draft) {
    draftMeta.value = st.draft
    draftRows.value = st.draft.rules.map((r) => ({ ...r, selected: true }))
    resetDocPage()
    clearTask()
    ElMessage.success(`《${name}》解析完成`)
    if (!st.draft.rules.length) {
      ElMessage.info('未抽出可机判规则，可将制度原文直接导入知识库（点「追加导入」）')
    }
  } else if (st.state === 'FAILURE') {
    clearTask()
    ElMessage.error(`《${name}》解析失败：${st.error || '未知原因'}。可重新上传重试。`)
  }
  // PENDING/STARTED：继续等下一轮
}

function startTimers() {
  stopTimers()
  pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS)
  elapsedTimer = setInterval(() => {
    elapsed.value += 1
    if (elapsed.value >= GIVE_UP_SECONDS) {
      const name = taskFilename.value
      clearTask()
      ElMessage.error(
        `《${name}》解析超过 ${GIVE_UP_SECONDS / 60} 分钟仍未完成，已停止等待。请确认后台任务进程（Celery worker）已启动，或重新上传。`,
      )
    }
  }, 1000)
}

// 重开对话框/刷新页面后续接未完成任务（草稿已就绪或在跟踪中则不动）
function restoreTask() {
  if (taskId.value || draftMeta.value) return
  const raw = sessionStorage.getItem(TASK_STORE_KEY)
  if (!raw) return
  try {
    const t = JSON.parse(raw) as { id?: string; filename?: string }
    if (!t.id) return
    taskId.value = t.id
    taskFilename.value = t.filename || '文档'
    elapsed.value = 0
    startTimers()
  } catch {
    sessionStorage.removeItem(TASK_STORE_KEY)
  }
}

// 用户主动放弃等待（worker没起等场景的逃生口；后台任务若仍完成，铃铛照样通知）
function abandonExtraction() {
  const name = taskFilename.value
  clearTask()
  ElMessage.info(`已停止跟踪《${name}》的解析进度。若后台仍解析成功，铃铛会通知；未收到通知可重新上传。`)
}

async function handleDocUpload(opts: UploadRequestOptions) {
  setRowErrors([])
  draftMeta.value = null
  draftRows.value = []
  clearTask() // 旧任务（若有）不再跟踪：界面只跟最新一次上传
  try {
    const res = await extractDocumentRules(opts.file) // 秒回：校验+落盘+派发
    taskId.value = res.task_id
    taskFilename.value = res.filename
    elapsed.value = 0
    saveTask()
    startTimers()
  } catch {
    // 拦截器已提示（400格式不符/文件超限）
  }
}

onUnmounted(stopTimers) // 组件卸载（切换页面）停轮询；sessionStorage里的任务重进时可续接

function removeRow(index: number) {
  draftRows.value.splice(index, 1)
}

async function handleConfirm(mode: 'append' | 'replace') {
  if (!draftMeta.value) return
  if (mode === 'replace') {
    await ElMessageBox.confirm(
      '替换模式将先清空现有制度知识库（policies）再写入新文档，历史案例库（similar_cases）不受影响。确定继续？',
      '替换全部确认',
      { type: 'warning', confirmButtonText: '替换导入', cancelButtonText: '取消' },
    )
  }
  confirming.value = true
  setRowErrors([])
  try {
    const res = await confirmDocumentImport({
      source: draftMeta.value.source,
      mode,
      rules: draftRows.value
        .filter((r) => r.selected)
        .map(({ selected: _selected, ...rule }) => rule),
      sections: draftMeta.value.sections,
    })
    if (res.imported || res.vector_written) {
      ElMessage.success(
        `成功导入 ${res.imported} 条规则${res.cleared_policies ? '，已清空旧制度库' : ''}，知识库写入 ${res.vector_written} 块`,
      )
    } else {
      ElMessage.warning('未导入任何内容（0条规则、知识库写入0块）')
    }
    if (!res.vector_available) {
      ElMessage.warning('知识库（Milvus）当前不可用：规则已保存，制度原文未入库，恢复后可重新导入')
    }
    emit('imported')
    visible.value = false
  } catch (err) {
    // 人工编辑后仍可能有非法行：渲染400逐行明细
    setRowErrors(extractRowErrors(err))
  } finally {
    confirming.value = false
  }
}

// ---------- 公共 ----------

function extractRowErrors(err: unknown): RowError[] {
  return (err as { response?: { data?: { errors?: RowError[] } } })?.response?.data?.errors ?? []
}

// 打开时惰性加载类别（草稿表格的类别下拉用）与库内代码（"已存在"提前标注）；
// 并续接上次未完成的文档解析任务
watch(visible, (v) => {
  if (!v) return
  restoreTask()
  if (!categories.value.length) {
    listCategories()
      .then((list) => (categories.value = list))
      .catch(() => {
        // 拦截器已提示
      })
  }
  listRules()
    .then((rules) => (existingCodes.value = new Set(rules.map((r) => r.code))))
    .catch(() => {
      // 拦截器已提示；拿不到就少一层提示，后端校验兜底
    })
})
</script>

<template>
  <el-dialog v-model="visible" title="导入规则" width="960px" top="5vh">
    <el-tabs v-model="activeTab">
      <!-- 通道一：JSON直导（文件→摘要+表格预览；原始JSON收纳进折叠面板） -->
      <el-tab-pane label="JSON 导入" name="json">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="mb-12"
          title="选择规则库JSON文件后自动解析为可编辑表格：可逐条修改、勾选要导入的行；带「提示」标注的行请先修正或取消勾选。导入时后端仍会全量校验（勾选行中有错则整体拒绝）。"
        />
        <el-collapse class="mb-12">
          <el-collapse-item title="格式示例（点击展开）" name="example">
            <pre class="json-example">{{ JSON_EXAMPLE }}</pre>
          </el-collapse-item>
        </el-collapse>
        <el-upload
          drag
          accept=".json"
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onJsonFileChange"
          class="mb-12"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖入 .json 文件或 <em>点击选择</em>（解析为下方可编辑表格）</div>
        </el-upload>

        <el-alert
          v-if="jsonParseError"
          type="error"
          :closable="false"
          show-icon
          class="mb-12"
          :title="jsonParseError"
        />
        <template v-if="jsonRows.length">
          <el-alert
            v-if="jsonCountMismatch !== null"
            type="warning"
            :closable="false"
            show-icon
            class="mb-12"
            :title="`文件声明 ${jsonCountMismatch} 条，实际解析 ${jsonRows.length} 条，请核对文件是否完整`"
          />
          <el-alert
            type="success"
            :closable="false"
            show-icon
            class="mb-12"
            :title="`已解析 ${jsonRows.length} 条规则${jsonParsed?.meta.length ? '（' + jsonParsed.meta.join('，') + '）' : ''}，请逐条核对（已勾选 ${checkedJsonCount} 条），修正「提示」标注后点击「校验并导入」`"
          />
          <RuleDraftTable
            :rows="pagedJsonRows"
            :categories="categories"
            :issue-of="jsonIssueOf"
            context="description"
            :index-offset="jsonOffset"
            @remove="removeJsonRow"
          />
          <el-pagination
            v-if="jsonRows.length > previewPageSize"
            v-model:current-page="previewPage"
            v-model:page-size="previewPageSize"
            :total="jsonRows.length"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            class="mt-12"
          />
        </template>

        <el-collapse v-model="rawJsonOpen" class="mb-12">
          <el-collapse-item
            :title="jsonRows.length ? '原始JSON（高级：可直接编辑，编辑后自动重新解析并重建表格）' : '未选文件？展开直接粘贴JSON'"
            name="raw"
          >
            <el-input
              v-model="jsonText"
              type="textarea"
              :rows="8"
              placeholder='[ {...}, {...} ] 或 { "rules": [...] }'
              @change="() => parseJsonPreview()"
            />
          </el-collapse-item>
        </el-collapse>
        <div class="dialog-actions">
          <el-button @click="visible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="jsonImporting"
            :disabled="!jsonRows.length"
            @click="handleJsonImport"
          >
            校验并导入（勾选{{ checkedJsonCount }}条）
          </el-button>
        </div>
      </el-tab-pane>

      <!-- 通道二：制度文档导入 -->
      <el-tab-pane label="文档导入 (docx/pdf)" name="doc">
        <!-- 解析中：状态卡片替换上传区（图标/文案/进度一眼可辨，且天然禁止再上传） -->
        <div v-if="extracting" class="extracting-card">
          <div class="extracting-main">
            <el-icon class="extracting-spin"><Loading /></el-icon>
            <div class="extracting-info">
              <div class="extracting-title">
                <span class="extracting-name" :title="taskFilename">{{ taskFilename }}</span>
                <el-tag size="small" type="primary" effect="light">解析中</el-tag>
                <span class="extracting-timer">{{ fmtElapsed(elapsed) }}</span>
              </div>
              <el-progress
                :percentage="100"
                :show-text="false"
                :stroke-width="8"
                striped
                striped-flow
              />
              <div class="extracting-eta">LLM 智能抽取约 1-5 分钟，超大文档可能接近 10 分钟</div>
            </div>
          </div>
          <div class="extracting-hint">
            解析在后台进行，您可以关闭此窗口去处理别的事：完成后右上角铃铛会通知您，
            期间重新打开本页会自动续接进度。请等当前文件解析完成后，再上传下一个文件。
          </div>
          <div class="extracting-actions">
            <el-button link type="danger" size="small" @click="abandonExtraction">
              不再等待此文件
            </el-button>
          </div>
        </div>
        <el-upload
          v-else
          drag
          accept=".docx,.pdf"
          :show-file-list="false"
          :http-request="handleDocUpload"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖入制度文档或点击上传（.docx / .pdf，≤10MB）</div>
        </el-upload>

        <template v-if="draftMeta">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="mt-12 mb-12"
            :title="`「${draftMeta.filename}」已解析 ${draftMeta.stats.sections} 个章节、抽出 ${draftRows.length} 条草稿规则（解析方式：${draftMeta.stats.method}）。请逐条核对「原文依据」后确认。`"
          />
          <RuleDraftTable
            :rows="pagedDraftRows"
            :categories="categories"
            :issue-of="docIssueOf"
            context="quote"
            :index-offset="docOffset"
            @remove="removeRow"
          />
          <el-pagination
            v-if="draftRows.length > docPageSize"
            v-model:current-page="docPage"
            v-model:page-size="docPageSize"
            :total="draftRows.length"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            class="mt-12"
          />
          <div class="dialog-actions">
            <el-button @click="visible = false">取消</el-button>
            <el-button
              type="primary"
              :loading="confirming"
              :disabled="!checkedCount"
              @click="handleConfirm('append')"
            >
              追加导入（勾选{{ checkedCount }}条）
            </el-button>
            <el-button type="danger" plain :loading="confirming" @click="handleConfirm('replace')">
              替换全部导入
            </el-button>
          </div>
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 400逐行错误明细（两通道共用，分页防长表） -->
    <el-alert v-if="rowErrors.length" type="error" :closable="false" show-icon class="mt-12">
      <el-table :data="pagedRowErrors" size="small" max-height="200">
        <el-table-column prop="index" label="行号" width="60" align="center" />
        <el-table-column prop="code" label="代码" width="150" />
        <el-table-column label="错误">
          <template #default="{ row }">{{ row.errors.join('；') }}</template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="rowErrors.length > errPageSize"
        v-model:current-page="errPage"
        v-model:page-size="errPageSize"
        :total="rowErrors.length"
        layout="total, prev, pager, next"
        class="mt-12"
      />
    </el-alert>
  </el-dialog>
</template>

<style scoped lang="scss">
.mb-12 {
  margin-bottom: 12px;
}

.mt-12 {
  margin-top: 12px;
}

.dialog-actions {
  margin-top: 12px;
  text-align: right;
}

.json-example {
  margin: 0;
  padding: 8px 12px;
  background: #f4f4f5;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

// 解析中状态卡片（替换上传拖拽区：状态语义清晰 + 禁止重复上传）
.extracting-card {
  padding: 18px 20px 12px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 8px;
  background: var(--el-color-primary-light-9);
}

.extracting-main {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.extracting-spin {
  flex-shrink: 0;
  margin-top: 2px;
  font-size: 22px;
  color: var(--el-color-primary);
  animation: rotating 1.6s linear infinite;
}

.extracting-info {
  flex: 1;
  min-width: 0;
}

.extracting-title {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}

.extracting-name {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// 等宽字体+右对齐：秒数跳动不挤压其余文字
.extracting-timer {
  margin-left: auto;
  font-family: ui-monospace, Consolas, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.extracting-eta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.extracting-hint {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color);
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.extracting-actions {
  margin-top: 4px;
  text-align: right;
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}
</style>
