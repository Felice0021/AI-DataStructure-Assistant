import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

/**
 * 开发服务器提供 MSW 的 Service Worker，生产构建不带它。
 *
 * 为什么不用 public/：Vite 会把 public/ 原样拷进 dist/，
 * 那样 mockServiceWorker.js 就成了生产产物的一部分（虽然不会被注册）。
 * 放到 src/mocks/ 由这里映射，产物里根本不会有这个文件。
 */
function serveMockWorker(): Plugin {
  return {
    name: 'serve-mock-worker',
    apply: 'serve',
    configureServer(server) {
      // 用 Vite 的 root 解析，不能用 import.meta.url：配置会被编译到临时目录
      const file = resolve(server.config.root, 'src/mocks/mockServiceWorker.js')
      server.middlewares.use('/mockServiceWorker.js', (_request, response) => {
        try {
          const body = readFileSync(file)
          response.setHeader('Content-Type', 'text/javascript; charset=utf-8')
          response.setHeader('Cache-Control', 'no-cache')
          response.statusCode = 200
          response.end(body)
        } catch {
          response.statusCode = 404
          response.end('mockServiceWorker.js not found')
        }
      })
    },
  }
}

// 后端固定 127.0.0.1:8001，前端必须同样用 127.0.0.1:5173。
// 用 localhost 打开会被后端 Origin 白名单拒绝（403 origin_rejected）。
export default defineConfig({
  plugins: [vue(), serveMockWorker()],
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
