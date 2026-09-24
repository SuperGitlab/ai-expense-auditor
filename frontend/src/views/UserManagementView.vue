<script setup lang="ts">
// 用户管理（admin）：列表 / 角色筛选 / 改角色 / 启停
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUsers, updateUserRole, updateUserStatus } from '@/api/user'
import { useUserStore } from '@/stores/user'
import { useClientPagination } from '@/composables/useClientPagination'
import type { UserInfo, UserRole } from '@/types'

const userStore = useUserStore()
const loading = ref(true)
const users = ref<UserInfo[]>([])
const { page: userPage, pageSize: userPageSize, paged: pagedUsers, reset: resetUserPage } =
  useClientPagination(users)
const roleFilter = ref<UserRole | ''>('')

const roleOptions: { value: UserRole; label: string }[] = [
  { value: 'admin', label: '管理员' },
  { value: 'finance', label: '财务' },
  { value: 'manager', label: '经理' },
  { value: 'employee', label: '员工' },
]

function roleLabel(role: UserRole) {
  return roleOptions.find((r) => r.value === role)?.label || role
}

async function load() {
  loading.value = true
  try {
    users.value = await getUsers(roleFilter.value || undefined)
  } finally {
    loading.value = false
  }
}

// 筛选变化：换了一组数据，回第1页
function search() {
  resetUserPage()
  load()
}

// 自己的行：下拉/开关禁用（后端也有双保险）
function isSelf(u: UserInfo) {
  return u.id === userStore.user?.id
}

async function handleRoleChange(u: UserInfo, role: UserRole) {
  const old = u.role
  try {
    await ElMessageBox.confirm(
      `确定将 ${u.full_name || u.username} 的角色由「${roleLabel(old)}」改为「${roleLabel(role)}」吗？`,
      '修改角色',
      { type: 'warning' },
    )
  } catch {
    u.role = old // 取消则还原下拉
    return
  }
  Object.assign(u, await updateUserRole(u.id, role))
  ElMessage.success('角色已更新')
}

async function handleStatusChange(u: UserInfo, active: boolean) {
  try {
    Object.assign(u, await updateUserStatus(u.id, active))
    ElMessage.success(active ? '已启用' : '已禁用')
  } catch {
    u.is_active = !active // 失败还原开关
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h2>用户管理</h2>
      <el-select
        v-model="roleFilter"
        placeholder="全部角色"
        clearable
        style="width: 160px"
        @change="search"
      >
        <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
      </el-select>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="pagedUsers" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column label="姓名" min-width="100">
          <template #default="{ row }">{{ row.full_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column label="部门" min-width="100">
          <template #default="{ row }">{{ row.department || '-' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="150">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              :disabled="isSelf(row)"
              size="small"
              @change="handleRoleChange(row, $event as UserRole)"
            >
              <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              :disabled="isSelf(row)"
              @change="handleStatusChange(row, $event as boolean)"
            />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            {{ row.created_at?.replace('T', ' ').slice(0, 16) }}
          </template>
        </el-table-column>
      </el-table>

      <div v-if="users.length > userPageSize" class="pagination-wrap">
        <el-pagination
          v-model:current-page="userPage"
          v-model:page-size="userPageSize"
          :total="users.length"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
