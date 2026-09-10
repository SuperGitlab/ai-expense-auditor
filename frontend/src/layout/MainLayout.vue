<script setup lang="ts">
// 主布局：左侧菜单（按角色显隐）+ 顶栏（通知铃铛/用户信息/退出）+ 内容区
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import {
  TYPE_LABELS,
  TYPE_TAG_TYPES,
  getNotifications,
  getUnreadCount,
  markAllRead,
  markRead,
} from '@/api/notification'
import type { NotificationItem } from '@/types'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const activeMenu = computed(() => route.path)

// 菜单项：roles为空表示所有登录角色可见
interface MenuItem {
  path: string
  title: string
  icon: string
  roles?: string[]
}

const menus = computed<MenuItem[]>(() => {
  const role = userStore.user?.role
  const all: MenuItem[] = [
    { path: '/dashboard', title: '工作台', icon: 'Odometer' },
    { path: '/expenses/new', title: '提交报销', icon: 'EditPen' },
    { path: '/expenses', title: '我的报销', icon: 'Tickets' },
    { path: '/expenses/all', title: '全部报销', icon: 'Files', roles: ['manager', 'finance', 'admin'] },
    { path: '/approvals', title: '审批中心', icon: 'Finished', roles: ['manager', 'finance', 'admin'] },
    { path: '/rules', title: '规则管理', icon: 'Setting', roles: ['admin'] },
    { path: '/users', title: '用户管理', icon: 'User', roles: ['admin'] },
    { path: '/reports', title: '数据报表', icon: 'DataAnalysis', roles: ['finance', 'admin'] },
  ]
  return all.filter((m) => !m.roles || (role && m.roles.includes(role)))
})

const pageTitle = computed(() => (route.meta.title as string) || '')

async function handleLogout() {
  await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' })
  userStore.logout()
  router.push('/login')
}

function handleCommand(command: string) {
  if (command === 'logout') handleLogout()
}

// ===== 站内通知 =====
const unreadCount = ref(0)
const notifications = ref<NotificationItem[]>([])
let notifyTimer: ReturnType<typeof setInterval> | undefined

async function loadUnread() {
  try {
    unreadCount.value = (await getUnreadCount()).count
  } catch {
    /* 轮询失败静默 */
  }
}

async function loadNotifications() {
  try {
    notifications.value = (await getNotifications(1, 10)).items
  } catch {
    /* 静默 */
  }
}

async function readOne(n: NotificationItem) {
  if (n.is_read) return
  await markRead(n.id)
  n.is_read = true
  unreadCount.value = Math.max(0, unreadCount.value - 1)
}

async function readAll() {
  await markAllRead()
  notifications.value.forEach((n) => (n.is_read = true))
  unreadCount.value = 0
}

function formatNotifyTime(iso: string) {
  return iso.replace('T', ' ').slice(0, 16)
}

onMounted(() => {
  loadUnread()
  notifyTimer = setInterval(loadUnread, 30000)
})
onUnmounted(() => notifyTimer && clearInterval(notifyTimer))
</script>

<template>
  <el-container class="layout">
    <!-- 左侧菜单 -->
    <el-aside width="220px" class="layout-aside">
      <div class="logo">
        <el-icon :size="22" color="#409eff"><Coin /></el-icon>
        <span class="logo-text">财务报销审核</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        background-color="#001529"
        text-color="#a6adb4"
        active-text-color="#ffffff"
      >
        <el-menu-item v-for="menu in menus" :key="menu.path" :index="menu.path">
          <el-icon><component :is="menu.icon" /></el-icon>
          <span>{{ menu.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <!-- 顶栏 -->
      <el-header class="layout-header">
        <div class="header-title">{{ pageTitle }}</div>
        <div class="header-right">
          <!-- 站内通知 -->
          <el-dropdown class="notify-drop" @visible-change="(v: boolean) => v && loadNotifications()">
            <span class="notify-bell">
              <el-badge :value="unreadCount" :hidden="!unreadCount" :max="99">
                <el-icon :size="18"><Bell /></el-icon>
              </el-badge>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <div v-if="!notifications.length" class="notify-empty">暂无通知</div>
                <div
                  v-for="n in notifications"
                  :key="n.id"
                  class="notify-item"
                  :class="{ unread: !n.is_read }"
                  @click="readOne(n)"
                >
                  <div class="notify-title">
                    <el-tag size="small" :type="TYPE_TAG_TYPES[n.type] || 'info'">
                      {{ TYPE_LABELS[n.type] || n.type }}
                    </el-tag>
                    <span>{{ n.title }}</span>
                  </div>
                  <div class="notify-content">{{ n.content }}</div>
                  <div class="notify-time">{{ formatNotifyTime(n.created_at) }}</div>
                </div>
                <div v-if="notifications.length" class="notify-footer" @click="readAll">
                  全部已读
                </div>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-avatar :size="30" class="user-avatar">
                {{ userStore.displayName.charAt(0) || '?' }}
              </el-avatar>
              <span class="user-name">{{ userStore.displayName }}</span>
              <el-tag size="small" type="info" effect="plain">{{ userStore.roleLabel }}</el-tag>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 内容区 -->
      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped lang="scss">
.layout {
  height: 100vh;
}

.layout-aside {
  background-color: #001529;

  .logo {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    height: 60px;
    color: #fff;
    font-size: 16px;
    font-weight: 600;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }

  .el-menu {
    border-right: none;
  }
}

.layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 24px;

  .header-title {
    font-size: 16px;
    font-weight: 600;
  }

  .user-info {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;

    .user-avatar {
      background-color: #409eff;
      color: #fff;
    }
  }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.notify-bell {
  display: flex;
  align-items: center;
  cursor: pointer;
  outline: none;
}

.notify-drop :deep(.el-dropdown-menu) {
  width: 320px;
  max-height: 400px;
  overflow-y: auto;
  padding: 4px 0;
}

.notify-empty {
  padding: 24px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}

.notify-item {
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid #f0f2f5;

  &:hover {
    background: #f5f7fa;
  }

  &.unread .notify-title span {
    font-weight: 600;
  }

  .notify-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #303133;
  }

  .notify-content {
    margin-top: 4px;
    font-size: 12px;
    color: #909399;
    white-space: pre-line;
  }

  .notify-time {
    margin-top: 2px;
    font-size: 12px;
    color: #c0c4cc;
  }
}

.notify-footer {
  padding: 10px 0;
  text-align: center;
  font-size: 13px;
  color: #409eff;
  cursor: pointer;
}

.layout-main {
  background-color: #f5f7fa;
  padding: 0;
  overflow-y: auto;
}
</style>
