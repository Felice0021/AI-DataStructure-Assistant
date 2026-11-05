import { createPinia } from 'pinia'
import { createApp } from 'vue'

import { setUnauthorizedHandler } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { resetAllPrivateState } from '@/stores/reset'

import App from './App.vue'
import './styles/main.css'

/**
 * 启动顺序：
 * 1. 需要时先启动 MSW（必须在任何请求之前）
 * 2. 挂 Pinia
 * 3. 把「401 清理」注入 apiClient —— 这是「异常页面不显示旧私人答案」的唯一入口
 * 4. 探测已有会话，再 mount，避免首屏闪一下未登录
 */
async function bootstrap(): Promise<void> {
  // 开发环境下默认启用 mock；要连真实后端请设 VITE_USE_MOCK=false
  if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCK !== 'false') {
    const { worker } = await import('./mocks/browser')
    // 用 warn 而不是 bypass：bypass 会把「mock 没覆盖的接口」悄悄打到真实后端，
    // 造成真数据与假数据混在一起、难以判断。warn 只在控制台提示，不阻断页面。
    await worker.start({ onUnhandledRequest: 'warn' })
  }

  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)

  setUnauthorizedHandler(() => {
    // 只有「原本已登录、随后失效」才提示；首次访问未登录的 401 属正常，不该报失效。
    const wasAuthenticated = useAuthStore().isAuthenticated
    resetAllPrivateState()
    // 顺序很重要：resetAllPrivateState 里的 clear() 会把 sessionExpired 复位，
    // 所以必须在它之后打标记，登录页才能解释「为什么被踢出来」。
    if (wasAuthenticated) useAuthStore().markSessionExpired()
  })

  await useAuthStore().fetchMe()
  app.mount('#app')
}

void bootstrap()
