import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from '@/api/auth'
import { ensureCsrf, hasCsrf, invalidateCsrf } from '@/api/csrf'
import { ApiError } from '@/api/http'
import { mockAnswered, mockKnowledgeBases, mockUser } from '@/mocks/fixtures'

import { useAskStore } from './ask'
import { useAuthStore } from './auth'
import { useKnowledgeBaseStore } from './knowledgeBase'
import { logoutAndReset, resetAllPrivateState, resetPrivateData } from './reset'

vi.mock('@/api/auth', () => ({
  authApi: { me: vi.fn(), login: vi.fn(), register: vi.fn(), logout: vi.fn() },
}))

describe('resetAllPrivateState', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('401 / 退出后不残留任何私人状态', () => {
    const auth = useAuthStore()
    const knowledgeBase = useKnowledgeBaseStore()
    const ask = useAskStore()

    auth.user = { ...mockUser }
    auth.status = 'authenticated'
    knowledgeBase.items = [...mockKnowledgeBases]
    knowledgeBase.selectedIds = [mockKnowledgeBases[0]!.id]
    ask.phase = 'answered'
    ask.result = mockAnswered
    ask.lastQuery = '栈和队列的区别'

    resetAllPrivateState()

    expect(auth.user).toBeNull()
    expect(auth.status).toBe('anonymous')
    expect(knowledgeBase.items).toHaveLength(0)
    expect(knowledgeBase.selectedIds).toHaveLength(0)
    expect(ask.phase).toBe('idle')
    expect(ask.result).toBeNull()
    expect(ask.lastQuery).toBe('')
  })

  it('清理是幂等的，可以重复调用', () => {
    const auth = useAuthStore()
    resetAllPrivateState()
    resetAllPrivateState()
    expect(auth.status).toBe('anonymous')
  })

  it('resetPrivateData 只清私人数据，不影响登录态（登录成功后用它防残留）', () => {
    const auth = useAuthStore()
    const ask = useAskStore()

    auth.user = { ...mockUser }
    auth.status = 'authenticated'
    auth.sessionExpired = true
    ask.phase = 'failed'
    ask.errorCode = 'unauthorized'
    ask.errorMessage = '登录状态已失效，请重新登录'

    resetPrivateData()

    // 私人数据被清掉：重新登录后不会再看到过时的「登录已失效」卡片
    expect(ask.phase).toBe('idle')
    expect(ask.errorMessage).toBe('')
    // 登录态保留：调用方紧接着会写入新的 user
    expect(auth.status).toBe('authenticated')
  })

  it('401 流程：先 resetAllPrivateState 再 markSessionExpired，提示才不会被 clear 掉', () => {
    const auth = useAuthStore()
    auth.user = { ...mockUser }
    auth.status = 'authenticated'

    resetAllPrivateState()
    auth.markSessionExpired()

    expect(auth.status).toBe('anonymous')
    expect(auth.sessionExpired).toBe(true)

    // 登录成功后提示自动消失
    auth.sessionExpired = false
    expect(auth.sessionExpired).toBe(false)
  })
})

describe('logoutAndReset 结果区分', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  function signIn(): void {
    const auth = useAuthStore()
    auth.user = { ...mockUser }
    auth.status = 'authenticated'
  }

  it('服务端退出成功 → ok，并且本地清空', async () => {
    signIn()
    vi.mocked(authApi.logout).mockResolvedValue(undefined)

    const outcome = await logoutAndReset()

    expect(outcome).toBe('ok')
    expect(useAuthStore().status).toBe('anonymous')
  })

  it('会话本就失效（401）→ 视为已退出，不当失败', async () => {
    signIn()
    vi.mocked(authApi.logout).mockRejectedValue(new ApiError(401, 'unauthorized', 'x'))

    const outcome = await logoutAndReset()

    expect(outcome).toBe('expired')
    expect(useAuthStore().status).toBe('anonymous')
  })

  it('退出请求真失败（500）→ 返回 failed，仍清空本地但需提示用户', async () => {
    signIn()
    vi.mocked(authApi.logout).mockRejectedValue(new ApiError(500, 'internal_error', 'x'))

    const outcome = await logoutAndReset()

    expect(outcome).toBe('failed')
    // 本机必须清干净，不能因为失败就把用户留在已登录界面
    expect(useAuthStore().status).toBe('anonymous')
    expect(useAuthStore().user).toBeNull()
  })

  it('网络不可用也算 failed', async () => {
    signIn()
    vi.mocked(authApi.logout).mockRejectedValue(new ApiError(0, 'network_error', 'x'))

    await expect(logoutAndReset()).resolves.toBe('failed')
  })

  it('退出失败时清掉本地 CSRF 缓存（否则重试会用旧会话派生的 token）', async () => {
    signIn()
    invalidateCsrf()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ csrf_token: 'a'.repeat(64) }), {
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    await ensureCsrf()
    expect(hasCsrf()).toBe(true)

    vi.mocked(authApi.logout).mockRejectedValue(new ApiError(500, 'internal_error', 'x'))
    await logoutAndReset()

    expect(hasCsrf()).toBe(false)
    vi.unstubAllGlobals()
  })

  it('退出成功同样作废 CSRF 缓存（Cookie 已变，旧 token 必然失效）', async () => {
    signIn()
    invalidateCsrf()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ csrf_token: 'b'.repeat(64) }), {
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    await ensureCsrf()

    vi.mocked(authApi.logout).mockResolvedValue(undefined)
    await logoutAndReset()

    expect(hasCsrf()).toBe(false)
    vi.unstubAllGlobals()
  })
})
