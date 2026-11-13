<script setup lang="ts">
import { errorMessage } from '@/composables/useErrorMessage'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
const kbStore = useKnowledgeBaseStore()
</script>

<template>
  <section class="course">
    <h2><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H3V4Zm18 0h-6a3 3 0 0 0-3 3v14a4 4 0 0 1 4-3h5V4Z" stroke-linejoin="round" /></svg>课程知识库</h2>
    <p v-if="kbStore.loading" class="state" role="status">正在加载课程资料…</p>
    <div v-else-if="kbStore.errorCode || kbStore.courseIssue" class="state" role="alert">
      <p>{{ kbStore.errorCode ? errorMessage(kbStore.errorCode) : kbStore.courseIssue }}</p>
      <button type="button" @click="kbStore.load()">重新加载</button>
    </div>
  </section>
</template>

<style scoped>
.course h2 { display: flex; align-items: center; gap: 9px; margin: 0; padding: 10px; color: #525252; font-size: 13px; font-weight: 550; }
.course svg { flex-shrink: 0; }
.state { margin: 0; padding: 0 10px 8px; color: #737373; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.state p { margin: 0 0 6px; }
.state button { padding: 0; border: 0; color: #404040; background: transparent; font-size: 12px; text-decoration: underline; cursor: pointer; }
</style>
