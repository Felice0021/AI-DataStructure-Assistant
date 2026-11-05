// @vitest-environment node
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { handlers } from './handlers'

const server = setupServer(...handlers)

beforeAll(() => {
  // 'error'：任何没有被 handler 命中的请求都会抛错。
  // 兜底 handler 存在时，请求应该永远被它接住，而不该漏到网络上。
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  server.resetHandlers()
})

afterAll(() => {
  server.close()
})

describe('mock 模式下未匹配请求被本地拦下', () => {
  it('未覆盖的 /api/v2 请求返回 501，不会发到真实后端', async () => {
    const response = await fetch('http://127.0.0.1:8001/api/v2/unknown-endpoint')

    expect(response.status).toBe(501)
    const body = (await response.json()) as { error: { code: string; message: string } }
    expect(body.error.code).toBe('mock_unhandled')
    // 提示里带出具体路径，方便定位是哪个接口漏了 handler
    expect(body.error.message).toContain('/api/v2/unknown-endpoint')
  })

  it('未覆盖的写请求同样被拦下（不会真的创建数据）', async () => {
    const response = await fetch('http://127.0.0.1:8001/api/v2/documents', {
      method: 'POST',
      headers: { 'X-CSRF-Token': 'a'.repeat(64) },
      body: '{}',
    })

    expect(response.status).toBe(501)
  })

  it('已覆盖的接口仍然走自己的 handler（兜底不影响正常路由）', async () => {
    const response = await fetch('http://127.0.0.1:8001/api/v2/auth/csrf')

    expect(response.status).toBe(200)
    expect(await response.json()).toHaveProperty('csrf_token')
  })
})
