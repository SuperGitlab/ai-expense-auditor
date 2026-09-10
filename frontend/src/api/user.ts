// 用户管理 API（admin）
import request from '@/utils/request'
import type { UserInfo, UserRole } from '@/types'

// 后端list接口返回裸数组（无分页包装），取前100条够用
export function getUsers(role?: UserRole): Promise<UserInfo[]> {
  return request.get('/users', { params: { page: 1, page_size: 100, role } })
}

export function updateUserRole(id: number, role: UserRole): Promise<UserInfo> {
  return request.patch(`/users/${id}/role`, { role })
}

export function updateUserStatus(id: number, isActive: boolean): Promise<UserInfo> {
  return request.patch(`/users/${id}/status`, { is_active: isActive })
}
