/**
 * MSW handlers。核心价值：让 apiClient 走真实网络路径
 * （自定义头、Cookie 语义、错误体解析）也能在无后端时跑通。
 *
 * 场景由 VITE_MOCK_SCENARIO 控制，也可以临时用 URL 参数覆盖（免重启，方便演示取证）：
 *   ?mock=answered      → 200 + status='answered'
 *   ?mock=refuse        → 200 + status='insufficient_evidence'
 *   ?mock=unavailable   → 503 + AskResponse & error
 *   ?mock=unauthorized  → /auth/me 与 /knowledge-bases 返回 401
 */

import { HttpResponse, delay, http } from 'msw'

import type { AskRequest, Credentials } from '@/types/api'

import {
  mockAnswered,
  mockCsrfToken,
  mockGenerationUnavailable,
  mockKnowledgeBases,
  mockRefused,
  mockUser,
  type MockScenario,
} from './fixtures'

const SCENARIOS: MockScenario[] = ['answered', 'refuse', 'unavailable', 'unauthorized']

/** 每次请求现算：URL 参数优先于环境变量，这样切换场景不用重启 dev server */
function currentScenario(): MockScenario {
  const fromEnv = import.meta.env.VITE_MOCK_SCENARIO as MockScenario | undefined
  const fallback: MockScenario = fromEnv && SCENARIOS.includes(fromEnv) ? fromEnv : 'answered'
  if (typeof window === 'undefined') return fallback
  const fromUrl = new URLSearchParams(window.location.search).get('mock')
  return fromUrl && (SCENARIOS as string[]).includes(fromUrl) ? (fromUrl as MockScenario) : fallback
}

/** 模拟后端的 CSRF 校验：没有合法的 X-CSRF-Token 就 403，逼真且能验证前端注入是否正确 */
function csrfGuard(request: Request): Response | null {
  const token = request.headers.get('X-CSRF-Token')
  if (!token || !/^[0-9a-f]{64}$/.test(token)) {
    return HttpResponse.json(
      { error: { code: 'csrf_rejected', message: 'CSRF token missing or invalid' } },
      { status: 403 },
    )
  }
  return null
}

// 每次都要新建 Response：复用同一个实例会导致第二次读 body 时报 "Body has already been read"
const unauthorized = () =>
  HttpResponse.json(
    { error: { code: 'unauthorized', message: 'Authentication required' } },
    { status: 401 },
  )

export const handlers = [
  http.get('*/api/v2/auth/csrf', async () => {
    await delay(30)
    return HttpResponse.json({ csrf_token: mockCsrfToken })
  }),

  http.post('*/api/v2/auth/register', async ({ request }) => {
    const rejected = csrfGuard(request)
    if (rejected) return rejected
    const body = (await request.json()) as Partial<Credentials>
    if (!body.email || !body.password) {
      return HttpResponse.json(
        { error: { code: 'invalid_request', message: 'Invalid request' } },
        { status: 422 },
      )
    }
    await delay(120)
    return HttpResponse.json({ user: mockUser }, { status: 201 })
  }),

  http.post('*/api/v2/auth/login', async ({ request }) => {
    const rejected = csrfGuard(request)
    if (rejected) return rejected
    const body = (await request.json()) as Partial<Credentials>
    await delay(150)
    if (!body.email || !body.password) {
      return HttpResponse.json(
        { error: { code: 'invalid_credentials', message: 'Invalid credentials' } },
        { status: 401 },
      )
    }
    return HttpResponse.json({ user: mockUser })
  }),

  http.get('*/api/v2/auth/me', async () => {
    await delay(60)
    if (currentScenario() === 'unauthorized') return unauthorized()
    return HttpResponse.json({ user: mockUser })
  }),

  http.post('*/api/v2/auth/logout', async ({ request }) => {
    const rejected = csrfGuard(request)
    if (rejected) return rejected
    await delay(60)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('*/api/v2/knowledge-bases', async ({ request }) => {
    await delay(80)
    if (currentScenario() === 'unauthorized') return unauthorized()
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? 50)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const page = mockKnowledgeBases.slice(offset, offset + limit)
    return HttpResponse.json({
      items: page,
      total: mockKnowledgeBases.length,
      limit,
      offset,
    })
  }),

  http.post('*/api/v2/rag/ask', async ({ request }) => {
    const rejected = csrfGuard(request)
    if (rejected) return rejected

    const body = (await request.json()) as Partial<AskRequest>
    await delay(700)

    if (!body.query || !Array.isArray(body.knowledge_base_ids) || body.knowledge_base_ids.length === 0) {
      return HttpResponse.json(
        { error: { code: 'invalid_request', message: 'Invalid request' } },
        { status: 422 },
      )
    }

    if (currentScenario() === 'unavailable') {
      return HttpResponse.json(mockGenerationUnavailable, { status: 503 })
    }
    if (currentScenario() === 'refuse') {
      return HttpResponse.json(mockRefused)
    }
    return HttpResponse.json(mockAnswered)
  }),
]
