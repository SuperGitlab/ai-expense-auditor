<script setup lang="ts">
// 草稿规则可编辑表格（文档抽取/JSON解析两通道共用）：
// 行首勾选=导入范围、行内控件=逐条修正、提示列=问题标注、删行；行数据由父层持有
import type { Category } from '@/types'
import { OPERATOR_MAP, RULE_FIELD_OPTIONS, RULE_TYPE_MAP, SEVERITY_MAP } from '@/constants'
import type { DraftRow } from '@/api/ruleImport'

withDefaults(
  defineProps<{
    rows: DraftRow[]
    categories: Category[]
    /** 每行的提示标签（row, 全局行号）=> issues：文档通道=后端轻校验，JSON通道=客户端镜像校验 */
    issueOf: (row: DraftRow, index: number) => string[]
    /** 首列内容：quote=原文依据（只读灰字），description=说明（可编辑） */
    context: 'quote' | 'description'
    /** 分页场景下当前页首行在全集中的偏移（全局行号=offset+页内序号） */
    indexOffset?: number
  }>(),
  { indexOffset: 0 },
)

const emit = defineEmits<{ remove: [index: number] }>()

// 这两个操作符只判存在性，不需要阈值
const NO_THRESHOLD_OPS = ['exists', 'not_exists']
</script>

<template>
  <el-table :data="rows" stripe size="small" max-height="420">
    <el-table-column width="38" align="center">
      <template #default="{ row }">
        <el-checkbox v-model="row.selected" />
      </template>
    </el-table-column>
    <el-table-column v-if="context === 'quote'" label="原文依据" min-width="170">
      <template #default="{ row }">
        <span class="quote">{{ row.quote || '（无）' }}</span>
      </template>
    </el-table-column>
    <el-table-column v-else label="说明" min-width="150">
      <template #default="{ row }">
        <el-input v-model="row.description" size="small" placeholder="选填" />
      </template>
    </el-table-column>
    <el-table-column label="名称" min-width="130">
      <template #default="{ row }">
        <el-input v-model="row.name" size="small" />
      </template>
    </el-table-column>
    <el-table-column label="代码" width="140">
      <template #default="{ row }">
        <el-input v-model="row.code" size="small" />
      </template>
    </el-table-column>
    <el-table-column label="类型" width="110">
      <template #default="{ row }">
        <el-select v-model="row.rule_type" size="small">
          <el-option
            v-for="(label, value) in RULE_TYPE_MAP"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
      </template>
    </el-table-column>
    <el-table-column label="类别" width="110">
      <template #default="{ row }">
        <el-select v-model="row.category_code" size="small" clearable placeholder="全类别">
          <el-option
            v-for="cat in categories"
            :key="cat.code"
            :label="cat.name"
            :value="cat.code"
          />
        </el-select>
      </template>
    </el-table-column>
    <el-table-column label="字段" width="130">
      <template #default="{ row }">
        <el-select v-model="row.field_name" size="small">
          <el-option
            v-for="f in RULE_FIELD_OPTIONS"
            :key="f.value"
            :label="f.label"
            :value="f.value"
          />
        </el-select>
      </template>
    </el-table-column>
    <el-table-column label="操作符" width="110">
      <template #default="{ row }">
        <el-select v-model="row.operator" size="small">
          <el-option
            v-for="(label, value) in OPERATOR_MAP"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
      </template>
    </el-table-column>
    <el-table-column label="阈值" width="100">
      <template #default="{ row }">
        <el-input
          v-model="row.threshold"
          size="small"
          :disabled="NO_THRESHOLD_OPS.includes(row.operator)"
        />
      </template>
    </el-table-column>
    <el-table-column label="严重度" width="95">
      <template #default="{ row }">
        <el-select v-model="row.severity" size="small">
          <el-option
            v-for="(meta, value) in SEVERITY_MAP"
            :key="value"
            :label="meta.label"
            :value="value"
          />
        </el-select>
      </template>
    </el-table-column>
    <el-table-column label="风险分" width="80" align="center">
      <template #default="{ row }">
        <el-input-number
          v-model="row.risk_points"
          size="small"
          :min="0"
          :max="100"
          controls-position="right"
          style="width: 100%"
        />
      </template>
    </el-table-column>
    <el-table-column label="提示" width="150">
      <template #default="{ row, $index }">
        <el-tag
          v-for="i in issueOf(row, indexOffset + $index)"
          :key="i"
          type="warning"
          size="small"
          class="issue-tag"
        >
          {{ i }}
        </el-tag>
        <span v-if="!issueOf(row, indexOffset + $index).length">-</span>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="55" fixed="right">
      <template #default="{ $index }">
        <el-button link type="danger" size="small" @click="emit('remove', indexOffset + $index)">
          删
        </el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped lang="scss">
.quote {
  color: #909399;
  font-size: 12px;
}

.issue-tag {
  margin: 2px 4px 2px 0;
  white-space: normal;
  height: auto;
  padding: 2px 6px;
}
</style>
