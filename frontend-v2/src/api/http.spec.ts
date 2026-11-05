import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { invalidateCsrf } from './csrf'
import { ApiError, request, setUnauthorizedHandler } from './http'

const TOKEN = 'b'.repeat(64)

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubFetch(route: (url: string, init: RequestInit) => Response) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : String(input)
    if (url.includes('/auth/csrf')) return json({ csrf_token: TOKEN })
    return route(url, init ?? {})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('apiClient', () => {
  beforeEach(() => {
    invalidateCsrf()
  })

  afterEach(() => {
    setUnauthorizedHandler(null)
    invalidateCsrf()
    vi.unstubAllGlobals()
  })

  it('401 触发全局清理回调', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    stubFetch(() => json({ error: { code: 'unauthorized', message: 'Authentication required' } }, 401))

    await expect(request('/knowledge-bases')).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('登录接口的 401 不触发全局清理（那是密码错误）', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    stubFetch(() => json({ error: { code: 'invalid_credentials', message: 'Invalid credentials' } }, 401))

    await expect(
      request('/auth/login', { method: 'POST', body: { email: 'a@b.c', password: 'x' }, skipAuthHandler: true }),
    ).rejects.toMatchObject({ status: 401, code: 'invalid_credentials' })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('解析运行时 422 形态 { error: { code } }', async () => {
    stubFetch(() => json({ error: { code: 'invalid_request', message: 'Invalid request' } }, 422))

    await expect(request('/rag/ask', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 422,
      code: 'invalid_request',
    })
  })

  it('兼容 openapi 声明的 { detail: [...] } 422 形态', async () => {
    stubFetch(() => json({ detail: [{ loc: ['body', 'query'], msg: 'required', type: 'missing' }] }, 422))

    await expect(request('/rag/ask', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 422,
      code: 'invalid_request',
    })
  })

  it('503 混合体：status 与 error.code 都要拿到', async () => {
    const body = {
      status: 'generation_unavailable',
      reason: 'generation_cloud_consent_required',
      answer: null,
      sources: [],
      retrieval_mode: 'hybrid',
      answer_mode: 'qa',
      rerank_applied: false,
      generation_model: null,
      latency_ms: 12.5,
      error: { code: 'generation_cloud_consent_required', message: 'consent required' },
    }
    stubFetch(() => json(body, 503))

    let error: ApiError | null = null
    try {
      await request('/rag/ask', { method: 'POST', body: {} })
    } catch (caught) {
      error = caught as ApiError
    }

    expect(error).toBeInstanceOf(ApiError)
    expect(error?.status).toBe(503)
    expect(error?.code).toBe('generation_cloud_consent_required')
  })

  it('写请求自动带 X-CSRF-Token 与 credentials: include', async () => {
    const fetchMock = stubFetch(() => json({ ok: true }))

    await request('/rag/ask', { method: 'POST', body: { query: 'q', knowledge_base_ids: ['k'] } })

    const postCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/rag/ask'))
    expect(postCall).toBeDefined()
    const init = postCall?.[1] as RequestInit
    expect(init.credentials).toBe('include')
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe(TOKEN)
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('204 返回 undefined 而不报错', async () => {
    stubFetch(() => new Response(null, { status: 204 }))

    await expect(request('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('业务 404 走 error 封装，不泄露成 detail', async () => {
    stubFetch(() => json({ error: { code: 'knowledge_base_not_found', message: 'Not found' } }, 404))

    await expect(request('/knowledge-bases/x')).rejects.toMatchObject({
      status: 404,
      code: 'knowledge_base_not_found',
    })
  })
})
