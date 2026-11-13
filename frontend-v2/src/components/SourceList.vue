<script setup lang="ts">
import type { AnswerSource } from '@/types/api'

defineProps<{
  sources: AnswerSource[]
  highlight: string | null
  open?: boolean
  idPrefix?: string
}>()
const emit = defineEmits<{ (event: 'toggle', open: boolean): void }>()
</script>

<template>
  <details v-if="sources.length > 0" class="sources" :open="open" @toggle="emit('toggle', ($event.target as HTMLDetailsElement).open)">
    <summary class="sources-title">资料来源（{{ sources.length }}）</summary>
    <ol class="source-list">
      <li
        v-for="source in sources"
        :id="`${idPrefix ? idPrefix + '-' : ''}source-${source.citation_id.replace(/[[\]]/g, '')}`"
        :key="source.citation_id"
        class="source-item"
        :class="{ 'is-active': highlight === source.citation_id }"
      >
        <span class="source-cite">{{ source.citation_id }}</span>
        <div class="source-body">
          <p class="source-name">{{ /^v1-course-(?:chapter-)?\d+\.txt$/i.test(source.source_filename) ? '课程资料（来源待核实）' : source.source_filename }}</p>
          <p class="source-meta">
            <span v-if="source.page_number !== null">第 {{ source.page_number }} 页</span>
            <span v-else>页码未知</span>
            <span v-if="source.section_title && !source.section_title.startsWith('V1:')">· {{ source.section_title }}</span>
          </p>
        </div>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.sources {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.sources-title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
}

.source-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #FFFFFF;
}

.source-item.is-active {
  border-color: #a3a3a3;
  background: #f5f5f5;
}

.source-cite {
  flex: 0 0 auto;
  height: fit-content;
  padding: 1px 5px;
  border-radius: 4px;
  background: #f1f1f1;
  color: #404040;
  font-size: 12px;
  font-weight: 500;
}

.source-body {
  min-width: 0;
}

.source-name {
  margin: 0 0 3px;
  font-size: 13px;
  color: var(--ink);
  word-break: break-all;
}

.source-meta {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
