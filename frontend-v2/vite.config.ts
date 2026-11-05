import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// 后端固定 127.0.0.1:8001，前端必须同样用 127.0.0.1:5173。
// 用 localhost 打开会被后端 Origin 白名单拒绝（403 origin_rejected）。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
    restoreMocks: true,
    // 关闭文件系统模块缓存：避免在某些受限环境下清理缓存目录失败导致启动报错
    cache: false,
  },
})
