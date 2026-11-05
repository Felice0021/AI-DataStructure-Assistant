<script setup lang="ts">
import { computed } from 'vue'

import type { AnswerSource } from '@/types/api'

/**
 * 安全渲染回答正文。
 *
 * 绝不使用 v-html：模型输出属于不可信内容，直接塞进 DOM 等于把 XSS 面交给模型。
 * 这里把正文按 [S1] 标记切成片段，文本片段走 {{ }} 插值（Vue 自动转义），
 * 只有能在本次 sources 里找到对应 citation_id 的标记才渲染成可点击按钮，
 * 编造的引用（例如 [S9]）降级为灰色纯文本。
 */

const props = defineProps<{
  text: string
  sources: AnswerSource[]
}>()

const emit = defineEmits<{
  (event: 'cite', citationId: string): void
}>()

interface Segment {
  key: string
  type: 'text' | 'cite'
  value: string
  known: boolean
}

const knownCitations = computed(() => new Set(props.sources.map((source) => source.citation_id)))

const segments = computed<Segment[]>(() => {
  const result: Segment[] = []
  const pattern = /\[S(\d+)\]/g
  let cursor = 0
  let index = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(props.text)) !== null) {
    if (match.index > cursor) {
      result.push({
        key: `t${index++}`,
        type: 'text',
        value: props.text.slice(cursor, match.index),
        known: true,
      })
    }
    result.push({
      key: `c${index++}`,
      type: 'cite',
      value: match[0],
      known: knownCitations.value.has(match[0]),
    })
    cursor = match.index + match[0].length
  }

  if (cursor < props.text.length) {
    result.push({
      key: `t${index++}`,
      type: 'text',
      value: props.text.slice(cursor),
      known: true,
    })
  }

  return result
})

function handleCite(citationId: string): void {
  emit('cite', citationId)
}
</script>

<template>
  <p class="answer-text">
    <template v-for="segment in segments" :key="segment.key">
      <button
        v-if="segment.type === 'cite' && segment.known"
        type="button"
        class="cite"
        :title="`查看来源 ${segment.value}`"
        @click="handleCite(segment.value)"
      >
        {{ segment.value }}
      </button>
      <span v-else-if="segment.type === 'cite'" class="cite-unknown" :title="'本次回答未返回该来源'">
        {{ segment.value }}
      </span>
      <span v-else>{{ segment.value }}</span>
    </template>
  </p>
</template>

<style scoped>
.answer-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.85;
  color: var(--ink);
}

.cite {
  display: inline;
  padding: 0 3px;
  margin: 0 1px;
  border: 0;
  border-radius: 4px;
  background: #e8f0fb;
  color: var(--brand);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  vertical-align: 1px;
  cursor: pointer;
}

.cite:hover {
  background: #d3e3f8;
}

.cite:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}

.cite-unknown {
  display: inline;
  padding: 0 3px;
  margin: 0 1px;
  border-radius: 4px;
  background: #f0f1f3;
  color: #98a0aa;
  font-size: 12px;
  vertical-align: 1px;
}
</style>
