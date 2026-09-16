// 路由：7个页面 + 登录态/角色守卫
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import MainLayout from '@/layout/MainLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '工作台' },
      },
      {
        path: 'expenses',
        name: 'expense-list',
        component: () => import('@/views/ExpenseListView.vue'),
        meta: { title: '我的报销' },
      },
      {
        path: 'expenses/new',
        name: 'expense-new',
        component: () => import('@/views/ExpenseSubmitView.vue'),
        meta: { title: '提交报销' },
      },
      {
        path: 'expenses/edit/:id',
        name: 'expense-edit',
        component: () => import('@/views/ExpenseSubmitView.vue'),
        meta: { title: '编辑报销' },
      },
      {
        path: 'expenses/all',
        name: 'expense-all',
        component: () => import('@/views/AllExpensesView.vue'),
        // manager/finance/admin 可进（后端API还会再校验一道）
        meta: { title: '全部报销', roles: ['manager', 'finance', 'admin'] },
      },
      {
        path: 'approvals',
        name: 'approvals',
        component: () => import('@/views/ApprovalCenterView.vue'),
        // manager/finance/admin 可进（后端API还会再校验一道）
        meta: { title: '审批中心', roles: ['manager', 'finance', 'admin'] },
      },
      {
        path: 'rules',
        name: 'rules',
        component: () => import('@/views/RuleManagementView.vue'),
        meta: { title: '规则管理', roles: ['admin'] },
      },
      {
        path: 'categories',
        name: 'categories',
        component: () => import('@/views/CategoryManagementView.vue'),
        meta: { title: '类别管理', roles: ['admin'] },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UserManagementView.vue'),
        meta: { title: '用户管理', roles: ['admin'] },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/ReportsView.vue'),
        meta: { title: '数据报表', roles: ['finance', 'admin'] },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局守卫：未登录跳登录页；角色不符弹提示并回工作台
router.beforeEach(async (to) => {
  const userStore = useUserStore()

  if (to.meta.public) {
    // 已登录访问登录页 → 直接进工作台
    if (userStore.isLoggedIn && to.path === '/login') return '/dashboard'
    return true
  }

  if (!userStore.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 刷新后store是空的：凭token拉一次用户信息
  if (!userStore.user) {
    try {
      await userStore.fetchUser()
    } catch {
      return '/login'
    }
  }

  const roles = to.meta.roles as string[] | undefined
  if (roles && userStore.user && !roles.includes(userStore.user.role)) {
    ElMessage.warning('当前角色无权访问该页面')
    return '/dashboard'
  }

  return true
})

export default router
