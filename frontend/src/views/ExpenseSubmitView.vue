<script setup lang="ts">
// 提交/编辑报销单：基础信息 + 动态明细行，保存后可选立即提交（触发AI审核）
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createExpense, getExpense, submitExpense, updateExpense } from '@/api/expense'
import { listCategories } from '@/api/category'
import { EXPENSE_TYPE_MAP, formatAmount } from '@/constants'
import type { Category, ExpenseType } from '@/types'

const route = useRoute()
const router = useRouter()

// 路由带 :id 即编辑模式（草稿/被驳回的单可改后重提）
const editId = computed(() => (route.params.id ? Number(route.params.id) : null))

const formRef = ref<FormInstance>()
const saving = ref(false)
const submitting = ref(false)
const categories = ref<Category[]>([])

const form = reactive({
  title: '',
  expense_type: 'travel' as ExpenseType,
  description: '',
  remark: '',
  items: [] as {
    category_id: number | null
    description: string
    amount: number | null
    expense_date: string
    invoice_no: string
    invoice_url: string
  }[],
})

const rules: FormRules = {
  title: [{ required: true, message: '请输入报销标题', trigger: 'blur' }],
  expense_type: [{ required: true, message: '请选择报销类型', trigger: 'change' }],
}

const totalAmount = computed(() =>
  form.items.reduce((sum, it) => sum + (Number(it.amount) || 0), 0),
)

function addItem() {
  form.items.push({
    category_id: null,
    description: '',
    amount: null,
    expense_date: '',
    invoice_no: '',
    invoice_url: '',
  })
}

function removeItem(index: number) {
  form.items.splice(index, 1)
}

// 明细行校验（动态行用el-form行内校验太绕，提交前手动检查）
function validateItems(): string | null {
  if (!form.items.length) return '至少填写一条费用明细'
  for (let i = 0; i < form.items.length; i++) {
    const it = form.items[i]
    const label = `第 ${i + 1} 条明细`
    if (!it.category_id) return `${label}：请选择费用类别`
    if (!it.description.trim()) return `${label}：请填写费用说明`
    if (!it.amount || it.amount <= 0) return `${label}：金额必须大于0`
    if (!it.expense_date) return `${label}：请选择费用日期`
  }
  return null
}

function buildPayload() {
  return {
    title: form.title,
    expense_type: form.expense_type,
    description: form.description || null,
    remark: form.remark || null,
    items: form.items.map((it) => ({
      category_id: it.category_id!,
      description: it.description,
      amount: Number(it.amount),
      expense_date: it.expense_date,
      invoice_no: it.invoice_no || null,
      invoice_url: it.invoice_url || null,
    })),
  }
}

// 保存（草稿）
async function handleSave() {
  await formRef.value?.validate()
  const err = validateItems()
  if (err) {
    ElMessage.warning(err)
    return
  }
  saving.value = true
  try {
    let expenseId: number
    if (editId.value) {
      const updated = await updateExpense(editId.value, buildPayload())
      expenseId = updated.id
      ElMessage.success('保存成功')
    } else {
      const created = await createExpense(buildPayload())
      expenseId = created.id
      ElMessage.success('报销单已保存为草稿')
    }
    // 询问是否立即提交（提交即触发AI审核工作流）
    try {
      await ElMessageBox.confirm(
        '是否立即提交审核？提交后 AI 将自动进行风险审核，低风险单据可自动通过。',
        '提交确认',
        { confirmButtonText: '立即提交', cancelButtonText: '暂不提交', type: 'info' },
      )
      await doSubmit(expenseId)
    } catch {
      router.push('/expenses')
    }
  } finally {
    saving.value = false
  }
}

async function doSubmit(expenseId: number) {
  submitting.value = true
  try {
    await submitExpense(expenseId)
    // 后端AI审核是异步跑的（提交立即返回），结果稍后在列表/详情查看
    ElMessage.success('已提交，AI 审核进行中，请稍后在列表查看结果')
    router.push('/expenses')
  } catch {
    // 提交接口报错（如状态不符）由拦截器提示；留在当前页
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  addItem() // 默认一行明细
  categories.value = await listCategories()

  // 编辑模式：加载已有数据回填
  if (editId.value) {
    const exp = await getExpense(editId.value)
    form.title = exp.title
    form.expense_type = exp.expense_type
    form.description = exp.description || ''
    form.remark = exp.remark || ''
    form.items = exp.items.map((it) => ({
      category_id: it.category_id,
      description: it.description,
      amount: Number(it.amount),
      expense_date: it.expense_date,
      invoice_no: it.invoice_no || '',
      invoice_url: it.invoice_url || '',
    }))
    if (!form.items.length) addItem()
  }
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>{{ editId ? '编辑报销单' : '提交报销单' }}</h2>
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px" style="max-width: 1100px">
      <el-card shadow="never" class="form-card">
        <template #header>基本信息</template>
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="报销标题" prop="title">
              <el-input v-model="form.title" placeholder="如：9月上海出差报销" maxlength="200" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="报销类型" prop="expense_type">
              <el-select v-model="form.expense_type" style="width: 100%">
                <el-option
                  v-for="(label, value) in EXPENSE_TYPE_MAP"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="报销说明">
              <el-input
                v-model="form.description"
                type="textarea"
                :rows="2"
                placeholder="补充说明费用事由（选填，供AI审核参考）"
              />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="1" placeholder="选填" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-card>

      <el-card shadow="never" class="form-card">
        <template #header>
          <div class="card-header-flex">
            <span>费用明细（金额合计：¥{{ formatAmount(totalAmount) }}）</span>
            <el-button type="primary" plain size="small" @click="addItem">
              <el-icon><Plus /></el-icon>&nbsp;添加明细
            </el-button>
          </div>
        </template>

        <el-table :data="form.items" border>
          <el-table-column type="index" label="#" width="46" align="center" />
          <el-table-column label="费用类别" width="180">
            <template #default="{ row }">
              <el-select v-model="row.category_id" placeholder="选择类别">
                <el-option
                  v-for="cat in categories"
                  :key="cat.id"
                  :label="cat.max_amount ? `${cat.name}（≤${cat.max_amount}元）` : cat.name"
                  :value="cat.id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="费用说明" min-width="180">
            <template #default="{ row }">
              <el-input v-model="row.description" placeholder="如：上海-北京 高铁二等座" />
            </template>
          </el-table-column>
          <el-table-column label="金额(元)" width="160">
            <template #default="{ row }">
              <el-input-number
                v-model="row.amount"
                :min="0.01"
                :precision="2"
                :controls="false"
                placeholder="0.00"
                style="width: 100%"
              />
            </template>
          </el-table-column>
          <el-table-column label="费用日期" width="170">
            <template #default="{ row }">
              <el-date-picker
                v-model="row.expense_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                :disabled-date="(d: Date) => d.getTime() > Date.now()"
                style="width: 100%"
              />
            </template>
          </el-table-column>
          <el-table-column label="发票号" width="170">
            <template #default="{ row }">
              <el-input v-model="row.invoice_no" placeholder="无发票可留空" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ $index }">
              <el-button
                link
                type="danger"
                :disabled="form.items.length <= 1"
                @click="removeItem($index)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          class="tip-alert"
          type="info"
          :closable="false"
          show-icon
          title="提示：无发票、超类别限额、金额与发票不符等信息会被 AI 审核识别；命中阻断规则的单据将被自动驳回。"
        />
      </el-card>

      <div class="form-actions">
        <el-button :loading="saving || submitting" @click="router.push('/expenses')">取消</el-button>
        <el-button type="primary" :loading="saving || submitting" @click="handleSave">
          {{ editId ? '保存修改' : '保存报销单' }}
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<style scoped lang="scss">
.form-card {
  margin-bottom: 16px;

  .card-header-flex {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
}

.tip-alert {
  margin-top: 12px;
}

.form-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding: 8px 0 24px;
}
</style>
