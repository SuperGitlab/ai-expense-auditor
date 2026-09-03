<script setup lang="ts">
// 规则管理（admin）：规则CRUD + 严重度标签
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createRule, deleteRule, listRules, updateRule } from '@/api/rule'
import { listCategories } from '@/api/category'
import { OPERATOR_MAP, RULE_TYPE_MAP, SEVERITY_MAP } from '@/constants'
import type { Category, Rule, RuleOperator, RuleSeverity, RuleType } from '@/types'

const loading = ref(false)
const rules = ref<Rule[]>([])
const categories = ref<Category[]>([])

const formRef = ref<FormInstance>()
const dialogVisible = ref(false)
const editingId = ref<number | null>(null) // null=新建
const saving = ref(false)

// 表单默认值（field_name取值与后端规则引擎约定：amount/expense_date/invoice_no/description）
const emptyForm = () => ({
  name: '',
  code: '',
  rule_type: 'amount_limit' as RuleType,
  category_id: null as number | null,
  field_name: 'amount',
  operator: 'gt' as RuleOperator,
  threshold: '',
  severity: 'warn' as RuleSeverity,
  risk_points: 10,
  description: '',
  is_active: true,
})

const dialog = reactive({ form: emptyForm() })

const FIELD_OPTIONS = [
  { value: 'amount', label: '金额(amount)' },
  { value: 'expense_date', label: '费用日期(expense_date)' },
  { value: 'invoice_no', label: '发票号(invoice_no)' },
  { value: 'description', label: '费用说明(description)' },
]

const rules_: FormRules = {
  name: [{ required: true, message: '请输入规则名称', trigger: 'blur' }],
  code: [{ required: true, message: '请输入规则代码', trigger: 'blur' }],
  field_name: [{ required: true, message: '请选择作用字段', trigger: 'change' }],
  operator: [{ required: true, message: '请选择操作符', trigger: 'change' }],
  threshold: [
    {
      // exists/not_exists不需要阈值，其余必填
      validator: (_rule: unknown, value: string, callback: (err?: Error) => void) => {
        const noThreshold = ['exists', 'not_exists'].includes(dialog.form.operator)
        if (!noThreshold && !String(value ?? '').trim()) {
          callback(new Error('请填写阈值'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

async function load() {
  loading.value = true
  try {
    const [ruleList, catList] = await Promise.all([listRules(), listCategories()])
    rules.value = ruleList
    categories.value = catList
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  dialog.form = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: Rule) {
  editingId.value = row.id
  dialog.form = {
    name: row.name,
    code: row.code,
    rule_type: row.rule_type,
    category_id: row.category_id,
    field_name: row.field_name,
    operator: row.operator,
    threshold: row.threshold ?? '',
    severity: row.severity,
    risk_points: row.risk_points,
    description: row.description ?? '',
    is_active: row.is_active,
  }
  dialogVisible.value = true
}

async function handleSave() {
  await formRef.value?.validate()
  saving.value = true
  try {
    const noThreshold = ['exists', 'not_exists'].includes(dialog.form.operator)
    const payload = {
      name: dialog.form.name,
      code: dialog.form.code,
      rule_type: dialog.form.rule_type,
      category_id: dialog.form.category_id,
      field_name: dialog.form.field_name,
      operator: dialog.form.operator,
      threshold: noThreshold ? null : dialog.form.threshold,
      severity: dialog.form.severity,
      risk_points: dialog.form.risk_points,
      description: dialog.form.description || null,
      is_active: dialog.form.is_active,
    }
    if (editingId.value) {
      // code不可改：更新接口也没有code字段
      const { code: _code, ...updatePayload } = payload
      await updateRule(editingId.value, updatePayload)
      ElMessage.success('规则已更新')
    } else {
      await createRule(payload)
      ElMessage.success('规则已创建')
    }
    dialogVisible.value = false
    load()
  } catch {
    // 拦截器已提示（如code重复409）
  } finally {
    saving.value = false
  }
}

async function handleDelete(row: Rule) {
  await ElMessageBox.confirm(
    `确定删除规则「${row.name}」？建议用"停用"代替删除。`,
    '删除确认',
    { type: 'warning' },
  )
  await deleteRule(row.id)
  ElMessage.success('已删除')
  load()
}

async function toggleActive(row: Rule) {
  await updateRule(row.id, { is_active: !row.is_active })
  row.is_active = !row.is_active
  ElMessage.success(row.is_active ? '已启用' : '已停用')
}

function categoryName(id: number | null): string {
  if (!id) return '全类别'
  return categories.value.find((c) => c.id === id)?.name || `类别${id}`
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>规则管理</h2>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新建规则
      </el-button>
    </div>

    <el-card shadow="never">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="mb-12"
        title="严重度说明：阻断(block)=命中自动驳回；转人工(review)=命中强制人工审批；计分(warn)=命中累计风险分。规则由确定性代码执行，不依赖大模型。"
      />

      <el-table v-loading="loading" :data="rules" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="规则名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="code" label="代码" width="170" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ RULE_TYPE_MAP[row.rule_type] || row.rule_type }}</template>
        </el-table-column>
        <el-table-column label="判定条件" min-width="200">
          <template #default="{ row }">
            <code class="rule-expr">
              {{ categoryName(row.category_id) }} · {{ row.field_name }}
              {{ OPERATOR_MAP[row.operator] || row.operator }}
              {{ row.threshold ?? '-' }}
            </code>
          </template>
        </el-table-column>
        <el-table-column label="严重度" width="90">
          <template #default="{ row }">
            <el-tag :type="SEVERITY_MAP[row.severity]?.type || 'info'" size="small">
              {{ SEVERITY_MAP[row.severity]?.label || row.severity }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="risk_points" label="风险分" width="80" align="center" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.is_active" @change="toggleActive(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑规则' : '新建规则'"
      width="620px"
    >
      <el-form ref="formRef" :model="dialog.form" :rules="rules_" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="规则名称" prop="name">
              <el-input v-model="dialog.form.name" placeholder="如：单张金额上限" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="规则代码" prop="code">
              <el-input
                v-model="dialog.form.code"
                :disabled="!!editingId"
                placeholder="如：amount_limit_total（唯一）"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="规则类型">
              <el-select v-model="dialog.form.rule_type" style="width: 100%">
                <el-option
                  v-for="(label, value) in RULE_TYPE_MAP"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="费用类别">
              <el-select v-model="dialog.form.category_id" clearable placeholder="全类别" style="width: 100%">
                <el-option
                  v-for="cat in categories"
                  :key="cat.id"
                  :label="cat.name"
                  :value="cat.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="作用字段" prop="field_name">
              <el-select v-model="dialog.form.field_name" style="width: 100%">
                <el-option v-for="f in FIELD_OPTIONS" :key="f.value" :label="f.label" :value="f.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="操作符" prop="operator">
              <el-select v-model="dialog.form.operator" style="width: 100%">
                <el-option
                  v-for="(label, value) in OPERATOR_MAP"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="阈值" prop="threshold">
              <el-input
                v-model="dialog.form.threshold"
                :disabled="['exists', 'not_exists'].includes(dialog.form.operator)"
                placeholder="数字/日期/逗号分隔集合"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="严重度">
              <el-select v-model="dialog.form.severity" style="width: 100%">
                <el-option
                  v-for="(meta, value) in SEVERITY_MAP"
                  :key="value"
                  :label="meta.label"
                  :value="value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="风险分">
              <el-input-number v-model="dialog.form.risk_points" :min="0" :max="100" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="规则说明">
              <el-input v-model="dialog.form.description" type="textarea" :rows="2" placeholder="选填" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="启用">
              <el-switch v-model="dialog.form.is_active" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.mb-12 {
  margin-bottom: 12px;
}

.rule-expr {
  background: #f4f4f5;
  color: #476582;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
</style>
