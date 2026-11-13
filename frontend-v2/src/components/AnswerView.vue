<script setup lang="ts">
import { computed, nextTick, ref, watch, useId } from 'vue'

import { reasonMessage } from '@/composables/useErrorMessage'
import type { AskResponse } from '@/types/api'

import AnswerText from './AnswerText.vue'
import SourceList from './SourceList.vue'

/**
 * 五态分发。三种「不成功」必须视觉可区分，不能混为一谈：
 * - refused（200 + insufficient_evidence）：正常拒答，资料不足，不是故障
 * - failed 502 validation_failed：生成结果未通过校验
 * - failed 503 generation_unavailable：生成服务不可用
 * 并且这三者都绝不能渲染成「回答成功」。
 */

const props = defineProps<{
  phase: 'idle' | 'loading' | 'answered' | 'refused' | 'failed'
  result: AskResponse | null
  errorCode: string | null
  errorStatus: number
  errorMessage: string
}>()

const emit = defineEmits<{
  (event: 'retry'): void
}>()

const sourcePrefix = useId()
const highlight = ref<string | null>(null)
const sourcesOpen = ref(false)
watch(() => props.result, () => { sourcesOpen.value = false; highlight.value = null })

const RETRIEVAL_LABELS: Record<string, string> = {
  bm25: 'BM25 关键词',
  dense: '向量检索',
  hybrid: '混合检索',
}

const ANSWER_MODE_LABELS: Record<string, string> = {
  auto: '自动',
  qa: '问答',
  exercise: '习题讲解',
  code: '代码分析',
}

const authorizationError = computed(() => props.errorCode?.includes('consent_required') === true)
const showRetry = computed(() => props.phase === 'failed' && ![401, 403].includes(props.errorStatus) && !authorizationError.value)

const refusalDetail = computed(() => reasonMessage(props.result?.reason ?? null))

async function onCite(citationId: string): Promise<void> {
  highlight.value = citationId
  sourcesOpen.value = true
  await nextTick()
  const element = document.getElementById(`${sourcePrefix}-source-${citationId.replace(/[[\]]/g, '')}`)
  try {
    element?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch {
    // 测试环境（jsdom）没有实现 scrollIntoView，忽略即可
  }
}
</script>

<template>
  <div class="answer-view">
    <p v-if="phase === 'idle'" class="placeholder">选择知识库后输入问题，回答会带上可核对的资料来源。</p>

    <div v-else-if="phase === 'loading'" class="loading" data-testid="answer-loading">
      <span class="spinner" aria-hidden="true"></span>
      <span>正在检索课程资料并生成回答…</span>
    </div>

    <section v-else-if="phase === 'answered' && result" class="card card-success" data-testid="answer-success">
      <header class="card-head">
        <span class="badge badge-success">已回答</span>
        <span class="head-meta">
          {{ result.generation_model?.startsWith('deterministic-') ? '确定性工程演示' : result.generation_model ? `生成模型：${result.generation_model}` : '生成模型未知' }} ·
          {{ RETRIEVAL_LABELS[result.retrieval_mode] ?? result.retrieval_mode }}
          · {{ ANSWER_MODE_LABELS[result.answer_mode] ?? result.answer_mode }}
          <span v-if="result.rerank_applied"> · 已重排</span>
          · {{ Math.round(result.latency_ms) }} ms
        </span>
      </header>
      <AnswerText :text="result.answer ?? ''" :sources="result.sources" @cite="onCite" />
      <SourceList :id-prefix="sourcePrefix" :sources="result.sources" :highlight="highlight" :open="sourcesOpen" @toggle="sourcesOpen = $event" />
    </section>

    <section v-else-if="phase === 'refused'" class="card card-warn" data-testid="answer-refused">
      <header class="card-head">
        <span class="badge badge-warn">资料不足</span>
        <span class="head-meta">这不是系统故障，而是当前资料无法支撑回答</span>
      </header>
      <p class="refusal-reason">{{ refusalDetail }}</p>
      <p class="hint">可以尝试：换用更具体的问法、勾选更多相关知识库，或先补充相关资料。</p>
    </section>

    <section v-else-if="phase === 'failed'" class="card card-error" data-testid="answer-error">
      <header class="card-head">
        <span class="badge badge-error">
          {{ authorizationError ? '需要处理授权' : errorStatus === 503 ? '服务不可用' : errorStatus === 502 ? '生成结果未通过校验' : '请求失败' }}
        </span>
        <span v-if="errorCode" class="head-meta">错误码 {{ errorCode }}</span>
      </header>
      <p class="error-message">{{ errorMessage }}</p>
      <p v-if="errorStatus === 503 && !authorizationError" class="hint">
        这与「资料不足」不同：那是正常结果，这是服务端出错。
      </p>
      <button v-if="showRetry" type="button" class="retry" @click="emit('retry')">重试</button>
    </section>
  </div>
</template>

<style scoped>
.answer-view {
  min-height: 120px;
}

.placeholder {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.loading {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-size: 13px;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--line);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.card {
  border: 0;
  border-radius: 0;
  padding: 0;
  background: #fff;
}

.card-success {
  border-left: 0;
}

.card-warn {
  border-left: 3px solid #d9a13b;
  background: #fffdf5;
}

.card-error {
  border-left: 3px solid #cf4b45;
  background: #fff8f8;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.badge {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
}

.badge-success {
  background: #e9f5ec;
  color: #2f6f45;
}

.badge-warn {
  background: #fdf1d8;
  color: #8a6114;
}

.badge-error {
  background: #fbe6e5;
  color: #9c322d;
}

.head-meta {
  font-size: 12px;
  color: var(--muted);
}
@media (max-width: 600px) {
  .card { padding: 12px; }
  .head-meta { flex-basis: 100%; }
}

.refusal-reason {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--ink);
}

.error-message {
  margin: 0 0 8px;
  font-size: 14px;
  color: #8e2b26;
}

.hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--muted);
}

.retry {
  margin-top: 12px;
  padding: 6px 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
}

.retry:hover {
  border-color: var(--brand);
  color: var(--brand);
}
</style>
