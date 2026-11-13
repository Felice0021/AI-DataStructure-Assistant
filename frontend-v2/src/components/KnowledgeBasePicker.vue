<script setup lang="ts">
import { onMounted } from 'vue'

import { errorMessage } from '@/composables/useErrorMessage'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'

const kbStore = useKnowledgeBaseStore()

onMounted(() => {
  if (kbStore.items.length === 0 && !kbStore.loading) {
    void kbStore.load()
  }
})

</script>

<template>
  <section class="picker">
    <header class="picker-head">
      <h2 class="picker-title">课程知识库</h2>
      <span class="picker-count">已选 {{ kbStore.selectedCount }} / {{ kbStore.total }}</span>
    </header>

    <p v-if="kbStore.limitNotice" class="notice" role="status">{{ kbStore.limitNotice }}</p>

    <div v-if="kbStore.loading" class="state">加载中…</div>

    <div v-else-if="kbStore.errorCode" class="state state-error">
      {{ errorMessage(kbStore.errorCode) }}
      <button type="button" class="link" @click="kbStore.load()">重新加载</button>
    </div>

    <div v-else-if="kbStore.isEmpty" class="state">还没有可用的知识库。<br />请联系管理员导入课程资料。</div>

    <template v-else>
      <div class="group">
        <label v-for="kb in kbStore.items" :key="kb.id" class="item" :title="kb.description || kb.name">
          <input type="checkbox" :checked="kbStore.isSelected(kb.id)"
            :disabled="kbStore.selectionFull && !kbStore.isSelected(kb.id)" @change="kbStore.toggle(kb.id)" />
          <span class="item-name">{{ kb.name }}</span>
        </label>
      </div>

      <p v-if="kbStore.truncated" class="state">
        仅显示前 {{ kbStore.items.length }} 个，共 {{ kbStore.total }} 个。
      </p>

      <div v-if="kbStore.items.length > 1" class="actions">
        <button type="button" class="link" @click="kbStore.selectAll()">全选</button>
        <button type="button" class="link" @click="kbStore.clearSelection()">清空</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.picker { display: flex; flex-direction: column; gap: 8px; }
.picker-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 0 10px; }
.picker-title { margin: 0; font-size: 12px; font-weight: 550; color: #525252; }
.picker-count { font-size: 11px; color: #737373; white-space: nowrap; }
.notice, .state { margin: 0; padding: 8px 10px; font-size: 12px; line-height: 1.6; color: #525252; }
.notice { background: #f5f5f5; border-radius: 8px; }
.group { display: flex; flex-direction: column; gap: 2px; }
.item { display: flex; align-items: flex-start; gap: 8px; padding: 8px 10px; border-radius: 8px; cursor: pointer; }
.item:hover { background: #f5f5f5; }
.item input { flex-shrink: 0; margin: 3px 0 0; accent-color: #404040; }
.item-name { min-width: 0; font-size: 13px; color: #262626; overflow-wrap: anywhere; }
.actions { display: flex; gap: 14px; padding: 0 10px; }
.link { padding: 0; border: 0; background: none; color: #525252; font-size: 12px; cursor: pointer; }
.link:hover { text-decoration: underline; }
</style>
