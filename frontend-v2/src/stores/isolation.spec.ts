import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, request, setUnauthorizedHandler } from '@/api/http'
import { knowledgeBaseApi } from '@/api/knowledgeBases'
import { ragApi } from '@/api/rag'
import { bumpEpoch } from '@/api/session'
import { mockAnswered, mockKnowledgeBases } from '@/mocks/fixtures'
import type { AskResponse, KnowledgeBaseList } from '@/types/api'

import { useAskStore } from './ask'
import { useKnowledgeBaseStore } from './knowledgeBase'
import { resetAllPrivateState } from './reset'

vi.mock('@/api/rag', () => ({ ragApi: { ask: vi.fn() } }))
vi.mock('@/api/knowledgeBases', () => ({
  knowledgeBaseApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}))
vi.mock('@/api/auth', () => ({
  authApi: { me: vi.fn(), login: vi.fn(), register: vi.fn(), logout: vi.fn() },
}))

const ASK_PARAMS = {
  query: '栈和队列的区别',
  knowledgeBaseIds: ['kb-1'],
  answerMode: 'auto' as const,
  retrievalMode: 'hybrid' as const,
}

describe('异步请求与会话隔离', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('退出登录后，未完成的问答结果不会写回页面', async () => {
    let release!: (value: AskResponse) => void
    vi.mocked(ragApi.ask).mockImplementation(
      () => new Promise<AskResponse>((resolve) => (release = resolve)),
    )

    const ask = useAskStore()
    const pending = ask.ask(ASK_PARAMS)
    expect(ask.phase).toBe('loading')

    resetAllPrivateState() // 等价于退出登录 / 401 清理
    expect(ask.phase).toBe('idle')

    release(mockAnswered)
    await pending

    expect(ask.phase).toBe('idle')
    expect(ask.result).toBeNull()
  })

  it('切换账号后，未完成的知识库列表不会写回页面', async () => {
    let release!: (value: KnowledgeBaseList) => void
    vi.mocked(knowledgeBaseApi.list).mockImplementation(
      () => new Promise<KnowledgeBaseList>((resolve) => (release = resolve)),
    )

    const kb = useKnowledgeBaseStore()
    const pending = kb.load()
    expect(kb.loading).toBe(true)

    resetAllPrivateState()

    release({ items: [...mockKnowledgeBases], total: mockKnowledgeBases.length, limit: 100, offset: 0 })
    await pending

    expect(kb.items).toHaveLength(0)
    expect(kb.total).toBe(0)
    expect(kb.loading).toBe(false)
  })

  it('旧会话迟到的 401 不会清理新会话', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    let release!: (value: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    )

    const pending = request('/anything').catch((error: unknown) => error)

    // 请求飞行期间用户已经换账号（登录成功会 bump 一次）
    bumpEpoch()

    release(
      new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'x' } }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const outcome = await pending

    expect(outcome).toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
    setUnauthorizedHandler(null)
    vi.unstubAllGlobals()
  })

  it('同一会话的 401 仍然要触发清理', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'x' } }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )

    await request('/anything').catch(() => undefined)

    expect(handler).toHaveBeenCalledTimes(1)
    setUnauthorizedHandler(null)
    vi.unstubAllGlobals()
  })

  it('选择超过后端上限时本地拦截，不发请求', async () => {
    const ask = useAskStore()

    await ask.ask({
      ...ASK_PARAMS,
      knowledgeBaseIds: Array.from({ length: 21 }, (_, i) => `kb-${i}`),
    })

    expect(ragApi.ask).not.toHaveBeenCalled()
    expect(ask.phase).toBe('failed')
    expect(ask.errorMessage).toContain('最多选择 20')
  })
})
