// 用户全局状态：token + 当前用户信息 + 角色判断
import { defineStore } from 'pinia'
import { fetchMe, loginApi } from '@/api/auth'
import type { UserInfo, UserRole } from '@/types'

const ROLE_LABELS: Record<UserRole, string> = {
  admin: '管理员',
  finance: '财务',
  manager: '部门经理',
  employee: '普通员工',
}

interface UserState {
  token: string
  user: UserInfo | null
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    token: localStorage.getItem('token') || '',
    user: null,
  }),

  getters: {
    isLoggedIn: (s) => !!s.token,
    role: (s): UserRole => s.user?.role ?? 'employee',
    roleLabel(): string {
      return this.user ? ROLE_LABELS[this.role] : ''
    },
    displayName: (s) => s.user?.full_name || s.user?.username || '',
    // 审批权限：manager/finance/admin
    canApprove: (s) => ['manager', 'finance', 'admin'].includes(s.user?.role ?? ''),
    // 报表权限：finance/admin
    canReport: (s) => ['finance', 'admin'].includes(s.user?.role ?? ''),
    // 打款权限：finance/admin
    canPay: (s) => ['finance', 'admin'].includes(s.user?.role ?? ''),
    isAdmin: (s) => s.user?.role === 'admin',
  },

  actions: {
    async login(username: string, password: string) {
      const result = await loginApi(username, password)
      this.token = result.access_token
      this.user = result.user
      localStorage.setItem('token', result.access_token)
    },

    async fetchUser() {
      this.user = await fetchMe()
    },

    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
    },
  },
})
