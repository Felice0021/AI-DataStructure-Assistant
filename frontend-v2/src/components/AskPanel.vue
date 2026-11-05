<script setup lang="ts">
import { computed, ref } from 'vue'

import { useAskStore } from '@/stores/ask'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import type { AnswerModeRequest, RetrievalMode } from '@/types/api'

import AnswerView from './AnswerView.vue'

const askStore = useAskStore()
const kbStore = useKnowledgeBaseStore()

const query = ref('')
const answerMode = ref<AnswerModeRequest>('auto')
const retrievalMode = ref<RetrievalMode>('hybrid')

const MAX_QUERY = 2000

const canSubmit = computed(
  () => query.value.trim().length > 0 && kbStore.selectedCount > 0 && !askStore.isLoading,
)

const blockReason = computed(() => {
  if (askStore.isLoading) return '正在处理上一条问题'
  if (kbStore.selectedCount === 0) return '请先在左侧勾选至少一个知识库'
  if (query.value.trim().length === 0) return '请输入问题'
  return ''
})

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  await askStore.ask({
    query: query.value,
    knowledgeBaseIds: [...kbStore.selectedIds],
    answerMode: answerMode.value,
    retrievalMode: retrievalMode.value,
  })
}

function onKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    void submit()
  }
}
</script>

<template>
  <section class="ask-panel">
    <div class="field">
      <label class="field-label" for="ask-query">问题</label>
      <textarea
        id="ask-query"
        v-model="query"
        class="textarea"
        rows="4"
        :maxlength="MAX_QUERY"
        placeholder="例如：栈和队列在操作受限方式上有什么区别？"
        @keydown="onKeydown"
      ></textarea>
      <div class="field-foot">
        <span>{{ query.length }} / {{ MAX_QUERY }}</span>
        <span>Ctrl + Enter 发送</span>
      </div>
    </div>

    <div class="row">
      <div class="field field-inline">
        <label class="field-label" for="ask-answer-mode">回答模式</label>
        <select id="ask-answer-mode" v-model="answerMode" class="select">
          <option value="auto">自动</option>
          <option value="qa">概念问答</option>
          <option value="exercise">习题讲解</option>
          <option value="code">代码分析</option>
        </select>
      </div>

      <div class="field field-inline">
        <label class="field-label" for="ask-retrieval-mode">检索方式</label>
        <select id="ask-retrieval-mode" v-model="retrievalMode" class="select">
          <option value="hybrid">混合检索</option>
          <option value="bm25">BM25 关键词</option>
          <option value="dense">向量检索</option>
        </select>
      </div>

      <div class="submit-area">
        <button type="button" class="submit" :disabled="!canSubmit" @click="submit">
          {{ askStore.isLoading ? '生成中…' : '提问' }}
        </button>
      </div>
    </div>

    <p v-if="blockReason" class="block-reason">{{ blockReason }}</p>

    <div class="answer-area">
      <AnswerView
        :phase="askStore.phase"
        :result="askStore.result"
        :error-code="askStore.errorCode"
        :error-status="askStore.errorStatus"
        :error-message="askStore.errorMessage"
        @retry="submit"
      />
    </div>
  </section>
</template>

<style scoped>
.ask-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-inline {
  flex: 0 0 auto;
}

.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
}

.textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink);
  background: #fff;
  resize: vertical;
}

.textarea:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(24, 95, 165, 0.12);
}

.field-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #9aa2ac;
}

.row {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
}

.select {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  font-family: inherit;
  font-size: 13px;
  color: var(--ink);
}

.submit-area {
  margin-left: auto;
}

.submit {
  padding: 9px 22px;
  border: 0;
  border-radius: 8px;
  background: var(--brand);
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.submit:disabled {
  background: #b9c2cc;
  cursor: not-allowed;
}

.block-reason {
  margin: -6px 0 0;
  font-size: 12px;
  color: #9aa2ac;
}

.answer-area {
  padding-top: 4px;
}
</style>
