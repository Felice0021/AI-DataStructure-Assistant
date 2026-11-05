<script setup lang="ts">
import { onMounted } from 'vue'

import { errorMessage } from '@/composables/useErrorMessage'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import type { KnowledgeBase } from '@/types/api'

const kbStore = useKnowledgeBaseStore()

onMounted(() => {
  if (kbStore.items.length === 0 && !kbStore.loading) {
    void kbStore.load()
  }
})

function visibilityLabel(kb: KnowledgeBase): string {
  return kb.visibility === 'private' ? '我的' : '公共'
}
</script>

<template>
  <section class="picker">
    <header class="picker-head">
      <h2 class="picker-title">知识库</h2>
      <span class="picker-count">已选 {{ kbStore.selectedCount }} / {{ kbStore.total }}</span>
    </header>

    <div v-if="kbStore.loading" class="state">加载中…</div>

    <div v-else-if="kbStore.errorCode" class="state state-error">
      {{ errorMessage(kbStore.errorCode) }}
      <button type="button" class="link" @click="kbStore.load()">重新加载</button>
    </div>

    <div v-else-if="kbStore.isEmpty" class="state">还没有可用的知识库。<br />请联系管理员导入课程资料。</div>

    <template v-else>
      <div v-if="kbStore.mine.length > 0" class="group">
        <p class="group-title">我的私人资料</p>
        <label v-for="kb in kbStore.mine" :key="kb.id" class="item">
          <input
            type="checkbox"
            :checked="kbStore.isSelected(kb.id)"
            @change="kbStore.toggle(kb.id)"
          />
          <span class="item-body">
            <span class="item-name">{{ kb.name }}</span>
            <span class="item-desc">{{ kb.description || '无说明' }}</span>
          </span>
          <span class="tag tag-private">{{ visibilityLabel(kb) }}</span>
        </label>
      </div>

      <div v-if="kbStore.shared.length > 0" class="group">
        <p class="group-title">公共课程资料</p>
        <label v-for="kb in kbStore.shared" :key="kb.id" class="item">
          <input
            type="checkbox"
            :checked="kbStore.isSelected(kb.id)"
            @change="kbStore.toggle(kb.id)"
          />
          <span class="item-body">
            <span class="item-name">{{ kb.name }}</span>
            <span class="item-desc">{{ kb.description || '无说明' }}</span>
          </span>
          <span class="tag tag-public">{{ visibilityLabel(kb) }}</span>
        </label>
      </div>

      <div class="actions">
        <button type="button" class="link" @click="kbStore.selectAll()">全选</button>
        <button type="button" class="link" @click="kbStore.clearSelection()">清空</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.picker-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.picker-title {
  margin: 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--ink);
}

.picker-count {
  font-size: 12px;
  color: var(--muted);
}

.state {
  padding: 14px 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--muted);
}

.state-error {
  color: #8e2b26;
}

.group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.group-title {
  margin: 0 0 2px;
  font-size: 12px;
  font-weight: 500;
  color: #9aa2ac;
}

.item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
}

.item:hover {
  border-color: var(--line);
  background: #fafbfc;
}

.item input {
  margin-top: 3px;
  accent-color: var(--brand);
}

.item-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.item-name {
  font-size: 13px;
  color: var(--ink);
  word-break: break-all;
}

.item-desc {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
  word-break: break-all;
}

.tag {
  flex: 0 0 auto;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
}

.tag-private {
  background: #eef3fb;
  color: #3a5f8f;
}

.tag-public {
  background: #eef7ef;
  color: #3c6b46;
}

.actions {
  display: flex;
  gap: 14px;
  padding-top: 2px;
}

.link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--brand);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.link:hover {
  text-decoration: underline;
}
</style>
