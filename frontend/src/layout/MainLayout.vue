<script setup lang="ts">
// 主布局：左侧菜单（按角色显隐）+ 顶栏（用户信息/退出）+ 内容区
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'

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

.layout-main {
  background-color: #f5f7fa;
  padding: 0;
  overflow-y: auto;
}
</style>
