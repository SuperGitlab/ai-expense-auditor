<script setup lang="ts">
// 类别管理（admin）：费用类别增删改停
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createCategory, deleteCategory, listCategories, updateCategory } from '@/api/category'
import { useClientPagination } from '@/composables/useClientPagination'
import type { Category } from '@/types'

const loading = ref(false)
const categories = ref<Category[]>([])
const { page: catPage, pageSize: catPageSize, paged: pagedCategories } =
  useClientPagination(categories)

const formRef = ref<FormInstance>()
const dialogVisible = ref(false)
const editingId = ref<number | null>(null) // null=新建
const saving = ref(false)

const emptyForm = () => ({
  name: '',
  code: '',
  max_amount: null as number | null,
  description: '',
})

const dialog = reactive({ form: emptyForm() })

const rules_: FormRules = {
  name: [{ required: true, message: '请输入类别名称', trigger: 'blur' }],
  code: [{ required: true, message: '请输入类别代码', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    // 管理页需要看到停用类别
    categories.value = await listCategories(true)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  dialog.form = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: Category) {
  editingId.value = row.id
  dialog.form = {
    name: row.name,
    code: row.code,
    max_amount: row.max_amount,
    description: row.description ?? '',
  }
  dialogVisible.value = true
}

async function handleSave() {
  await formRef.value?.validate()
  saving.value = true
  try {
    const payload = {
      name: dialog.form.name,
      max_amount: dialog.form.max_amount,
      description: dialog.form.description || null,
    }
    if (editingId.value) {
      // code 创建后不可改，编辑不提交code
      await updateCategory(editingId.value, payload)
      ElMessage.success('类别已更新')
    } else {
      await createCategory({ ...payload, code: dialog.form.code })
      ElMessage.success('类别已创建')
    }
    dialogVisible.value = false
    load()
  } catch {
    // 拦截器已提示（如code重复409）
  } finally {
    saving.value = false
  }
}

async function handleDelete(row: Category) {
  await ElMessageBox.confirm(
    `删除「${row.name}」：绑定它的规则将被停用并解绑；若存在历史报销明细，类别将转为停用而非物理删除。`,
    '删除确认',
    { type: 'warning' },
  )
  const res = await deleteCategory(row.id)
  const ruleNote = res.hidden_rules ? `，${res.hidden_rules} 条绑定规则已停用` : ''
  if (res.deleted) {
    ElMessage.success(`已删除${ruleNote}`)
  } else {
    ElMessage.warning(`存在历史报销明细，已停用（未物理删除）${ruleNote}`)
  }
  load()
}

async function toggleActive(row: Category) {
  try {
    Object.assign(row, await updateCategory(row.id, { is_active: !row.is_active }))
    ElMessage.success(row.is_active ? '已启用' : '已停用')
  } catch {
    // 失败时row未变，开关随model-value自动还原
  }
}

function formatAmount(v: number | null) {
  if (v === null || v === undefined) return '-'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>类别管理</h2>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新建类别
      </el-button>
    </div>

    <el-card shadow="never">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="mb-12"
        title="费用类别用于报销明细行与规则绑定。删除类别会自动停用并解绑其规则；被历史明细引用的类别只停用不物理删除。"
      />
      <el-table v-loading="loading" :data="pagedCategories" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="code" label="代码" width="140" />
        <el-table-column label="单次上限" width="110" align="right">
          <template #default="{ row }">{{ formatAmount(row.max_amount) }}</template>
        </el-table-column>
        <el-table-column label="说明" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
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

      <div v-if="categories.length > catPageSize" class="pagination-wrap">
        <el-pagination
          v-model:current-page="catPage"
          v-model:page-size="catPageSize"
          :total="categories.length"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
        />
      </div>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑类别' : '新建类别'" width="480px">
      <el-form ref="formRef" :model="dialog.form" :rules="rules_" label-width="90px">
        <el-form-item label="类别名称" prop="name">
          <el-input v-model="dialog.form.name" placeholder="如：培训费" />
        </el-form-item>
        <el-form-item label="类别代码" prop="code">
          <el-input
            v-model="dialog.form.code"
            :disabled="!!editingId"
            placeholder="如：training（唯一，创建后不可改）"
          />
        </el-form-item>
        <el-form-item label="单次上限">
          <el-input-number
            v-model="dialog.form.max_amount"
            :min="0"
            :precision="2"
            controls-position="right"
            style="width: 100%"
            placeholder="留空不限制"
          />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="dialog.form.description" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
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

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
