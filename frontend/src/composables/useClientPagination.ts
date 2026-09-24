// 前端分页：接口全量返回的列表 → 当前页切片渲染
// （报销单列表是服务端分页 query.page → items/total，不适用本组合式函数）
import { computed, ref, watch } from 'vue'
import type { Ref } from 'vue'

/**
 * @param source 全量数据（ref 或 computed）
 * @param defaultSize 每页条数默认值（可在 el-pagination 里切换 20/50/100）
 */
export function useClientPagination<T>(source: Ref<T[]>, defaultSize = 20) {
  const page = ref(1)
  const pageSize = ref(defaultSize)

  // 换每页条数回到第1页，避免停留在大页码上出现空页
  watch(pageSize, () => (page.value = 1))
  // 删行/数据替换导致页码越界：自动收回最后一页
  watch(
    () => source.value.length,
    (len) => {
      const max = Math.max(1, Math.ceil(len / pageSize.value))
      if (page.value > max) page.value = max
    },
  )

  const paged = computed(() =>
    source.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value),
  )
  /** 当前页首行在全集中的偏移（全局行号=offset+页内序号） */
  const offset = computed(() => (page.value - 1) * pageSize.value)
  const reset = () => (page.value = 1)

  return { page, pageSize, paged, offset, reset }
}
