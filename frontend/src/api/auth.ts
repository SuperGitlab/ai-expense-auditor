// 认证相关 API
import request from '@/utils/request'
import type { LoginResult, UserInfo } from '@/types'

export function loginApi(username: string, password: string): Promise<LoginResult> {
  return request.post('/auth/login-json', { username, password })
}

export function fetchMe(): Promise<UserInfo> {
  return request.get('/auth/me')
}
