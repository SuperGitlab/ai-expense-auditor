// 发票文件上传 API
import request from '@/utils/request'

export interface UploadResult {
  url: string
  filename: string
  size: number
}

export function uploadInvoice(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  return request.post('/uploads', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
