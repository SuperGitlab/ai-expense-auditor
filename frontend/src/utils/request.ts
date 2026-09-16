// axios 统一封装：注入Token / 统一错误提示 / 401自动跳登录
import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

// 自定义请求配置：轮询类请求置 true 可跳过统一错误弹窗（避免闪断刷屏）
declare module 'axios' {
  export interface AxiosRequestConfig {
    skipErrorMessage?: boolean
  }
}

// AI审核走真实LLM调用，耗时较长，超时放宽到3分钟
const request = axios.create({
  baseURL: '/api', // 后端路由本身带 /api 前缀，vite代理直接透传
  timeout: 180000,
})

// 请求拦截：注入 Authorization
request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 从后端错误响应里提取人类可读信息
// FastAPI的detail可能是字符串（业务异常）或数组（Pydantic参数校验失败）
function extractErrorMessage(error: unknown): string {
  const resp = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
  if (!resp) {
    return '网络异常或服务不可用，请稍后重试'
  }
  const detail = resp.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'object' && d !== null && 'msg' in d ? String(d.msg) : ''))
      .filter(Boolean)
      .join('；')
  }
  return `请求失败（HTTP ${resp.status}）`
}

// 响应拦截：统一弹错误提示；401清token跳登录
request.interceptors.response.use(
  (response) => {
    // 直接返回业务数据（调用方拿到的就是后端的JSON body）
    return response.data
  },
  (error) => {
    const resp = (error as { response?: { status?: number } }).response
    const message = extractErrorMessage(error)

    if (resp?.status === 401) {
      // 登录过期/未登录：清凭据回登录页
      localStorage.removeItem('token')
      if (router.currentRoute.value.path !== '/login') {
        ElMessage.error('登录已过期，请重新登录')
        router.push('/login')
      } else {
        // 登录页本身的401 = 用户名或密码错误
        ElMessage.error(message || '用户名或密码错误')
      }
    } else if (!error.config?.skipErrorMessage) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default request
