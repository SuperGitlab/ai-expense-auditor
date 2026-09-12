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

// 上传并OCR识别：返回票面五字段（缺失为空串），识别失败 fields 为 null
export interface OcrFields {
  '发票号': string
  '费用日期': string
  '金额(元)': string
  '费用说明': string
  '费用类别': string
  category_id: number | null
}

export interface UploadOcrResult extends UploadResult {
  fields: OcrFields | null
}

export function uploadInvoiceOcr(file: File): Promise<UploadOcrResult> {
  const form = new FormData()
  form.append('file', file)
  return request.post('/uploads/ocr', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
