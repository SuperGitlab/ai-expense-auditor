<script setup lang="ts">
// 规则导入对话框（admin）：JSON直导 + 制度文档(docx/pdf)智能导入两通道
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadRequestOptions } from 'element-plus'
import { confirmDocumentImport, extractDocumentRules, importRulesJson } from '@/api/ruleImport'
import type { DraftRule, ExtractionDraft, RowError } from '@/api/ruleImport'
import { listCategories } from '@/api/category'
import { OPERATOR_MAP, RULE_FIELD_OPTIONS, RULE_TYPE_MAP, SEVERITY_MAP } from '@/constants'
import type { Category } from '@/types'

const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{ imported: [] }>()

const activeTab = ref<'json' | 'doc'>('json')
const categories = ref<Category[]>([])
const rowErrors = ref<RowError[]>([]) // 400逐行明细（两通道共用渲染）

// ---------- JSON通道 ----------

const jsonText = ref('')
const jsonImporting = ref(false)

const JSON_EXAMPLE = JSON.stringify(
  [
    {
      name: '餐饮单笔限额500元',
      code: 'MEAL_500',
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
  jsonText.value = await file.raw.text()
}

async function handleJsonImport() {
  rowErrors.value = []
  let parsed: unknown
  try {
    parsed = JSON.parse(jsonText.value)
  } catch {
    ElMessage.error('JSON 解析失败，请检查格式')
    return
  }
  const rules = Array.isArray(parsed) ? parsed : (parsed as { rules?: unknown })?.rules
  if (!Array.isArray(rules) || !rules.length) {
    ElMessage.error('请提供规则数组：[ {...}, {...} ] 或 { "rules": [...] }')
    return
  }
  jsonImporting.value = true
  try {
    const res = await importRulesJson(rules)
    ElMessage.success(`成功导入 ${res.imported} 条规则`)
    emit('imported')
    visible.value = false
  } catch (err) {
    // 拦截器已弹detail toast；这里取逐行明细渲染错误表
    rowErrors.value = extractRowErrors(err)
  } finally {
    jsonImporting.value = false
  }
}

// ---------- 文档通道 ----------

interface DraftRow extends DraftRule {
  selected: boolean
}

const extracting = ref(false)
const confirming = ref(false)
const draftMeta = ref<ExtractionDraft | null>(null) // sections/stats/source（待确认回传）
const draftRows = ref<DraftRow[]>([]) // 草稿行（带勾选态）

const checkedCount = computed(() => draftRows.value.filter((r) => r.selected).length)

async function handleDocUpload(opts: UploadRequestOptions) {
  rowErrors.value = []
  draftMeta.value = null
  draftRows.value = []
  extracting.value = true
  try {
    const res = await extractDocumentRules(opts.file)
    draftMeta.value = res
    draftRows.value = res.rules.map((r) => ({ ...r, selected: true }))
    if (!res.rules.length) {
      ElMessage.info('未抽出可机判规则，可将制度原文直接导入知识库（点「追加导入」）')
    }
  } catch {
    // 拦截器已提示（422扫描件/502抽取失败/400格式不符）
  } finally {
    extracting.value = false
  }
}

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
  rowErrors.value = []
  try {
    const res = await confirmDocumentImport({
      source: draftMeta.value.source,
      mode,
      rules: draftRows.value
        .filter((r) => r.selected)
        .map(({ selected: _selected, ...rule }) => rule),
      sections: draftMeta.value.sections,
    })
    if (res.imported || res.chroma_written) {
      ElMessage.success(
        `成功导入 ${res.imported} 条规则${res.cleared_policies ? '，已清空旧制度库' : ''}，知识库写入 ${res.chroma_written} 块`,
      )
    } else {
      ElMessage.warning('未导入任何内容（0条规则、知识库写入0块）')
    }
    if (!res.chroma_available) {
      ElMessage.warning('知识库（ChromaDB）当前不可用：规则已保存，制度原文未入库，恢复后可重新导入')
    }
    emit('imported')
    visible.value = false
  } catch (err) {
    // 人工编辑后仍可能有非法行：渲染400逐行明细
    rowErrors.value = extractRowErrors(err)
  } finally {
    confirming.value = false
  }
}

// ---------- 公共 ----------

function extractRowErrors(err: unknown): RowError[] {
  return (err as { response?: { data?: { errors?: RowError[] } } })?.response?.data?.errors ?? []
}

// 打开时惰性加载类别（草稿表格的类别下拉用）
watch(visible, (v) => {
  if (v && !categories.value.length) {
    listCategories()
      .then((list) => (categories.value = list))
      .catch(() => {
        // 拦截器已提示
      })
  }
})
</script>

<template>
  <el-dialog v-model="visible" title="导入规则" width="960px" top="5vh">
    <el-tabs v-model="activeTab">
      <!-- 通道一：JSON直导 -->
      <el-tab-pane label="JSON 导入" name="json">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="mb-12"
          title="JSON 须与规则表字段对齐（类别用 category_code 引用）。全量校验：任一行失败则整体拒绝，不写入任何数据。"
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
          <div class="el-upload__text">拖入 .json 文件或 <em>点击选择</em>（内容读入下方文本框）</div>
        </el-upload>
        <el-input
          v-model="jsonText"
          type="textarea"
          :rows="10"
          placeholder='也可直接粘贴：[ {...}, {...} ] 或 { "rules": [...] }'
        />
        <div class="dialog-actions">
          <el-button @click="visible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="jsonImporting"
            :disabled="!jsonText.trim()"
            @click="handleJsonImport"
          >
            校验并导入
          </el-button>
        </div>
      </el-tab-pane>

      <!-- 通道二：制度文档导入 -->
      <el-tab-pane label="文档导入 (docx/pdf)" name="doc">
        <el-upload
          drag
          accept=".docx,.pdf"
          :show-file-list="false"
          :http-request="handleDocUpload"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            {{ extracting ? '正在解析并抽取规则（约10-60秒，请勿关闭）…' : '拖入制度文档或点击上传（.docx / .pdf，≤10MB）' }}
          </div>
        </el-upload>

        <template v-if="draftMeta">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="mt-12 mb-12"
            :title="`「${draftMeta.filename}」已解析 ${draftMeta.stats.sections} 个章节、抽出 ${draftRows.length} 条草稿规则（解析方式：${draftMeta.stats.method}）。请逐条核对「原文依据」后确认。`"
          />
          <el-table v-loading="extracting" :data="draftRows" stripe size="small" max-height="420">
            <el-table-column width="38" align="center">
              <template #default="{ row }">
                <el-checkbox v-model="row.selected" />
              </template>
            </el-table-column>
            <el-table-column label="原文依据" min-width="170">
              <template #default="{ row }">
                <span class="quote">{{ row.quote || '（无）' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="130">
              <template #default="{ row }">
                <el-input v-model="row.name" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="代码" width="140">
              <template #default="{ row }">
                <el-input v-model="row.code" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-select v-model="row.rule_type" size="small">
                  <el-option
                    v-for="(label, value) in RULE_TYPE_MAP"
                    :key="value"
                    :label="label"
                    :value="value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="类别" width="110">
              <template #default="{ row }">
                <el-select v-model="row.category_code" size="small" clearable placeholder="全类别">
                  <el-option
                    v-for="cat in categories"
                    :key="cat.code"
                    :label="cat.name"
                    :value="cat.code"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="字段" width="130">
              <template #default="{ row }">
                <el-select v-model="row.field_name" size="small">
                  <el-option
                    v-for="f in RULE_FIELD_OPTIONS"
                    :key="f.value"
                    :label="f.label"
                    :value="f.value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作符" width="110">
              <template #default="{ row }">
                <el-select v-model="row.operator" size="small">
                  <el-option
                    v-for="(label, value) in OPERATOR_MAP"
                    :key="value"
                    :label="label"
                    :value="value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="阈值" width="100">
              <template #default="{ row }">
                <el-input
                  v-model="row.threshold"
                  size="small"
                  :disabled="['exists', 'not_exists'].includes(row.operator)"
                />
              </template>
            </el-table-column>
            <el-table-column label="严重度" width="95">
              <template #default="{ row }">
                <el-select v-model="row.severity" size="small">
                  <el-option
                    v-for="(meta, value) in SEVERITY_MAP"
                    :key="value"
                    :label="meta.label"
                    :value="value"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="风险分" width="80" align="center">
              <template #default="{ row }">
                <el-input-number v-model="row.risk_points" size="small" :min="0" :max="100" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="提示" width="150">
              <template #default="{ row }">
                <el-tag v-for="i in row.issues" :key="i" type="warning" size="small" class="issue-tag">
                  {{ i }}
                </el-tag>
                <span v-if="!row.issues.length">-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="55" fixed="right">
              <template #default="{ $index }">
                <el-button link type="danger" size="small" @click="removeRow($index)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
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

    <!-- 400逐行错误明细（两通道共用） -->
    <el-alert v-if="rowErrors.length" type="error" :closable="false" show-icon class="mt-12">
      <el-table :data="rowErrors" size="small" max-height="200">
        <el-table-column prop="index" label="行号" width="60" align="center" />
        <el-table-column prop="code" label="代码" width="150" />
        <el-table-column label="错误">
          <template #default="{ row }">{{ row.errors.join('；') }}</template>
        </el-table-column>
      </el-table>
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

.quote {
  color: #909399;
  font-size: 12px;
}

.issue-tag {
  margin: 2px 4px 2px 0;
  white-space: normal;
  height: auto;
  padding: 2px 6px;
}
</style>
