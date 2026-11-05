import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ensureCsrf, hasCsrf, invalidateCsrf, refreshCsrf } from './csrf'

const TOKEN = 'a'.repeat(64)

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('csrf token 管理', () => {
  beforeEach(() => {
    invalidateCsrf()
    vi.unstubAllGlobals()
  })

  it('并发调用只发一次 GET /auth/csrf', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({ csrf_token: TOKEN }))
    vi.stubGlobal('fetch', fetchMock)

    const tokens = await Promise.all([ensureCsrf(), ensureCsrf(), ensureCsrf()])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(tokens).toEqual([TOKEN, TOKEN, TOKEN])
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v2/auth/csrf')
  })

  it('已有缓存时不再请求', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({ csrf_token: TOKEN }))
    vi.stubGlobal('fetch', fetchMock)

    await ensureCsrf()
    await ensureCsrf()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(hasCsrf()).toBe(true)
  })

  it('invalidateCsrf 之后会重新请求（登录/登出后场景）', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse({ csrf_token: TOKEN }))
    vi.stubGlobal('fetch', fetchMock)

    await ensureCsrf()
    invalidateCsrf()
    await refreshCsrf()

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('响应缺少 csrf_token 时报错，不返回半成品', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => jsonResponse({ token: 'x' })))

    await expect(ensureCsrf()).rejects.toThrow(/csrf_token/)
  })

  it('请求失败时报错，不缓存空值', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => jsonResponse({}, 500)))

    await expect(ensureCsrf()).rejects.toThrow(/HTTP 500/)
    expect(hasCsrf()).toBe(false)
  })
})
