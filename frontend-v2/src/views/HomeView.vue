<script setup lang="ts">
import { ref } from 'vue'

import AskPanel from '@/components/AskPanel.vue'
import AuthPanel from '@/components/AuthPanel.vue'
import KnowledgeBasePicker from '@/components/KnowledgeBasePicker.vue'
import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'

const auth = useAuthStore()
const leaving = ref(false)

/** 当前 mock 场景：URL 参数优先（与 handlers 的取值逻辑保持一致） */
function currentMockScenario(): string {
  if (typeof window !== 'undefined') {
    const fromUrl = new URLSearchParams(window.location.search).get('mock')
    if (fromUrl) return fromUrl
  }
  return import.meta.env.VITE_MOCK_SCENARIO ?? 'answered'
}

/** 只在开发 + mock 模式下显示，提醒当前答案来自合成数据，不代表真实质量 */
const mockHint =
  import.meta.env.DEV && import.meta.env.VITE_USE_MOCK !== 'false'
    ? `模拟数据 · ${currentMockScenario()}`
    : ''

async function onLogout(): Promise<void> {
  leaving.value = true
  try {
    await logoutAndReset()
  } finally {
    leaving.value = false
  }
}
</script>

<template>
  <AuthPanel v-if="!auth.isAuthenticated" />

  <div v-else class="app">
    <header class="app-header">
      <div class="brand">
        <span class="brand-name">数据结构 AI 助教</span>
        <span class="brand-version">V2</span>
      </div>

      <div class="header-right">
        <span v-if="mockHint" class="mock-hint" :title="'当前数据来自 MSW 模拟，非真实课程问答质量'">
          {{ mockHint }}
        </span>
        <span class="user">{{ auth.email }}</span>
        <span class="role">{{ auth.roleLabel }}</span>
        <button type="button" class="logout" :disabled="leaving" @click="onLogout">
          {{ leaving ? '退出中…' : '退出' }}
        </button>
      </div>
    </header>

    <main class="app-main">
      <aside class="sidebar">
        <KnowledgeBasePicker />
      </aside>
      <section class="content">
        <AskPanel />
      </section>
    </main>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.brand-name {
  font-size: 15px;
  font-weight: 500;
  color: var(--ink);
}

.brand-version {
  font-size: 11px;
  color: var(--muted);
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: 4px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mock-hint {
  padding: 2px 8px;
  border-radius: 999px;
  background: #fdf1d8;
  color: #8a6114;
  font-size: 11px;
}

.user {
  font-size: 13px;
  color: var(--ink);
}

.role {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f2f4f7;
  color: var(--muted);
}

.logout {
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  font-family: inherit;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
}

.logout:hover {
  border-color: #cf4b45;
  color: #9c322d;
}

.app-main {
  display: flex;
  flex: 1;
  align-items: flex-start;
  gap: 20px;
  padding: 24px 28px 48px;
  max-width: 1180px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.sidebar {
  flex: 0 0 296px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
  position: sticky;
  top: 24px;
}

.content {
  flex: 1;
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
}

@media (max-width: 860px) {
  .app-main {
    flex-direction: column;
  }

  .sidebar {
    flex: 0 0 auto;
    width: 100%;
    position: static;
    box-sizing: border-box;
  }

  .content {
    width: 100%;
    box-sizing: border-box;
  }
}
</style>
