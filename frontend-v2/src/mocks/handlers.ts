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

import type { AskRequest, Credentials, KnowledgeBase } from '@/types/api'

import {
  mockAnswered,
  mockCsrfToken,
  mockGenerationUnavailable,
  mockKnowledgeBases,
  mockRefused,
  mockUser,
  type MockScenario,
} from './fixtures'

const SCENARIOS: MockScenario[] = [
  'answered',
  'refuse',
  'unavailable',
  'unauthorized',
  'logout-fail',
  'many-kbs',
]

/** 每次请求现算：URL 参数优先于环境变量，这样切换场景不用重启 dev server */
function currentScenario(): MockScenario {
  const fromEnv = import.meta.env.VITE_MOCK_SCENARIO as MockScenario | undefined
  const fallback: MockScenario = fromEnv && SCENARIOS.includes(fromEnv) ? fromEnv : 'answered'
  if (typeof window === 'undefined') return fallback
  const fromUrl = new URLSearchParams(window.location.search).get('mock')
  return fromUrl && (SCENARIOS as string[]).includes(fromUrl) ? (fromUrl as MockScenario) : fallback
}

/**
 * 演示/取证用：?delay=3000 让响应额外慢 3 秒。
 * 用来制造「请求还在飞」的时间窗，肉眼验证退出/切换账号后旧响应不会写回页面。
 */
function extraDelay(): number {
  if (typeof window === 'undefined') return 0
  const ms = Number(new URLSearchParams(window.location.search).get('delay'))
  return Number.isFinite(ms) && ms > 0 && ms <= 30_000 ? ms : 0
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

/** 25 个知识库（> 后端 20 的上限），用于演示全选截断与限额提示 */
function manyKnowledgeBases(): KnowledgeBase[] {
  return Array.from({ length: 25 }, (_, index) => {
    const isPublic = index % 3 === 0
    return {
      id: `44444444-4444-4444-8444-${String(index).padStart(12, '0')}`,
      owner_id: isPublic ? null : mockUser.id,
      name: `课程资料 ${index + 1}`,
      description: isPublic ? '公共课程资料' : '私人上传的资料',
      visibility: isPublic ? 'public' : 'private',
      index_version: 1,
      created_at: '2026-10-10T09:00:00Z',
      updated_at: '2026-10-20T09:00:00Z',
    } satisfies KnowledgeBase
  })
}

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
    if (currentScenario() === 'logout-fail') {
      return HttpResponse.json(
        { error: { code: 'internal_error', message: 'Logout failed' } },
        { status: 500 },
      )
    }
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('*/api/v2/knowledge-bases', async ({ request }) => {
    await delay(80 + extraDelay())
    if (currentScenario() === 'unauthorized') return unauthorized()
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? 50)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    // many-kbs：25 个库，用来验证「一次最多 20 个」的截断与提示
    const source = currentScenario() === 'many-kbs' ? manyKnowledgeBases() : mockKnowledgeBases
    const page = source.slice(offset, offset + limit)
    return HttpResponse.json({
      items: page,
      total: source.length,
      limit,
      offset,
    })
  }),

  // Mock uses no cloud provider and therefore has no cloud grants.
  http.get('*/api/v2/knowledge-bases/:id/cloud-consents', () => HttpResponse.json([])),
  http.get('*/api/v2/knowledge-bases/:id/cloud-consents/targets', () => HttpResponse.json([])),

  http.post('*/api/v2/rag/ask', async ({ request }) => {
    const rejected = csrfGuard(request)
    if (rejected) return rejected

    const body = (await request.json()) as Partial<AskRequest>
    await delay(700 + extraDelay())

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

  /**
   * 兜底：mock 模式下，任何没有被上面覆盖的 /api/v2/ 请求就地拦下。
   *
   * 为什么必须有：`onUnhandledRequest: 'warn'` 只是控制台提示，请求仍会真的发出去——
   * 若本机后端在跑，就会拿到真数据混进 mock 演示里，很难分辨。
   * 这条 handler 必须放在数组最后（MSW 按顺序匹配，先命中先用）。
   */
  http.all('*/api/v2/*', ({ request }) => {
    const { pathname } = new URL(request.url)
    return HttpResponse.json(
      {
        error: {
          code: 'mock_unhandled',
          message: `Mock 未覆盖该请求：${request.method} ${pathname}`,
        },
      },
      { status: 501 },
    )
  }),
]
